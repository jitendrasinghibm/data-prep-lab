import argparse
import json
import re
import sys
import urllib
from argparse import ArgumentParser
from typing import Any
from urllib.parse import urlparse

import pyarrow as pa
import ray
from data_processing.data_access import DataAccess, DataAccessFactory, DataAccessLocal
from data_processing.ray import (
    DefaultTableTransformConfiguration,
    DefaultTableTransformRuntime,
    TransformLauncher,
)
from data_processing.transform import AbstractTableTransform
from data_processing.utils import get_logger
from dotenv import load_dotenv
from ray.actor import ActorHandle


logger = get_logger(__name__)


BAD_WORD_DIR = "cos-optimal-llm-pile/bluepile-processing/docq/ldnoobw/"
MODEL_DIR = "cos-optimal-llm-pile/bluepile-processing/lm_sp/"


short_name = "docquality"
arg_prefix = short_name

ft_lang_key = f"{arg_prefix}_ft_lang"
""" Key holds the name of the ft_lang"""
drop_column_if_existed_key = f"{arg_prefix}_drop_column_if_existed_key"


class DocQualityTransform(AbstractTableTransform):
    """
    Implements various docuement quality metrics to documents in a pyarrow Table.
    """

    def __init__(self, config: dict):
        """
        Initialize based on the dictionary of configuration information.
        This is generally called with configuration parsed from the CLI arguments defined
        by the companion runtime, NOOPTransformRuntime.  If running inside the RayMutatingDriver,
        these will be provided by that class with help from the RayMutatingDriver.
        """
        from doc_c4_statistics import c4_load_ldnoobw_words

        ########## Changed to metaKenLM
        from perplexity import KenLMModel

        super().__init__(config)
        self.warning_issued = False
        self.ft_lang = config["ft_lang"]
        self.bad_word_filepath = f"{BAD_WORD_DIR}{self.ft_lang}"
        self.re_pattern = c4_load_ldnoobw_words(ft_lang=self.ft_lang, file_path=self.bad_word_filepath)
        strip_accent = True
        self.klm = KenLMModel.from_pretrained(model_path=MODEL_DIR, language=self.ft_lang, strip_accent=strip_accent)
        if "drop_column_if_existed" in config:
            self.drop_column_if_existed = config["drop_column_if_existed"]
        else:
            self.drop_column_if_existed = True

    def transform(self, table: pa.Table) -> tuple[list[pa.Table], dict]:

        from doc_c4_statistics import (
            c4_contain_pattern_ratio,
            c4_contains_ldnoobw_words,
            c4_sentence_count,
        )
        from doc_Gopher_statistics import (
            compute_average_japanese_sentence_length,
            compute_bullet_point_ellipsis_alphabet_word_ratio,
            compute_word_statistics,
            contains_common_English_words,
            find_first_japanese_alphabet_position,
        )

        """
        Put Transform-specific to convert one Table to another Table.
        This implementation makes no modifications so effectively implements a copy of the input parquet to the output folder, without modification.
        """
        new_columns = [
            "docq_total_words",
            "docq_mean_word_len",
            "docq_symbol_to_word_ratio",
            "docq_sentence_count",
            "docq_lorem_ipsum_ratio",
            "docq_curly_bracket_ratio",
            "docq_contain_bad_word",
            "docq_avg_ja_sentence_len",
            "docq_first_ja_alphabet_pos",
            "metakenlm_docq_perplex_score",
            "docq_contain_common_en_words",
            "docq_bullet_point_ratio",
            "docq_ellipsis_line_ratio",
            "docq_alphabet_word_ratio",
        ]
        for column in new_columns:
            if column in table.column_names:
                if self.drop_column_if_existed:
                    if not self.warning_issued:
                        # print(f"WARNING: drop existing column {column}. {input_parquet_path}")
                        print(f"WARNING: drop existing column {column}")
                        self.warning_issued = True
                    table = table.drop(column)
                else:
                    print(
                        f"ERROR: existing column {column} found and drop_column_if_existed is false. "
                        f"Terminating..."
                    )
                    exit(-1)

        docq_total_words = []
        docq_mean_word_len = []
        docq_symbol_to_word_ratio = []
        docq_sentence_count = []
        docq_curly_bracket_ratio = []
        docq_lorem_ipsum_ratio = []
        docq_contain_bad_word = []
        docq_bullet_point_ratio = []
        docq_ellipsis_line_ratio = []
        docq_alphabet_word_ratio = []
        docq_contain_common_en_words = []
        docq_perplex_score = []
        if self.ft_lang == "ja":
            # for japanese language, add 2 extra columns for 2 heuristic rules:
            docq_avg_ja_sentence_len = []
            docq_first_ja_alphabet_pos = []

        for text in table[self.col_name].to_pylist():
            total_words, mean_word_len, symbol_to_word_ratio = compute_word_statistics(text)
            docq_total_words.append(total_words)
            docq_mean_word_len.append(mean_word_len)
            docq_symbol_to_word_ratio.append(symbol_to_word_ratio)

            docq_sentence_count.append(c4_sentence_count(text, ft_lang=self.ft_lang))

            docq_lorem_ipsum_ratio.append(
                c4_contain_pattern_ratio(text, pattern="lorem ipsum", ft_lang=self.ft_lang, normalize_text=True)
            )
            curly_bracket_ratio = 0.0
            for sign in ["{", "}"]:
                curly_bracket_ratio += c4_contain_pattern_ratio(
                    text, pattern=sign, ft_lang=self.ft_lang, normalize_text=False
                )
            docq_curly_bracket_ratio.append(curly_bracket_ratio)
            docq_contain_bad_word.append(c4_contains_ldnoobw_words(text, self.re_pattern))

            (
                bullet_point_ratio,
                ellipsis_line_ratio,
                alphabet_word_ratio,
            ) = compute_bullet_point_ellipsis_alphabet_word_ratio(text)
            docq_bullet_point_ratio.append(bullet_point_ratio)
            docq_ellipsis_line_ratio.append(ellipsis_line_ratio)
            docq_alphabet_word_ratio.append(alphabet_word_ratio)

            docq_contain_common_en_words.append(contains_common_English_words(text, self.ft_lang))

            docq_perplex_score.append(self.klm.get_perplexity(text))

            if self.ft_lang == "ja":
                docq_avg_ja_sentence_len.append(compute_average_japanese_sentence_length(text))
                docq_first_ja_alphabet_pos.append(find_first_japanese_alphabet_position(text))

        table = table.append_column("docq_total_words", pa.array(docq_total_words))
        table = table.append_column("docq_mean_word_len", pa.array(docq_mean_word_len))
        table = table.append_column("docq_symbol_to_word_ratio", pa.array(docq_symbol_to_word_ratio))
        table = table.append_column("docq_sentence_count", pa.array(docq_sentence_count))
        table = table.append_column("docq_lorem_ipsum_ratio", pa.array(docq_lorem_ipsum_ratio))
        table = table.append_column("docq_curly_bracket_ratio", pa.array(docq_curly_bracket_ratio))
        table = table.append_column("docq_contain_bad_word", pa.array(docq_contain_bad_word))
        table = table.append_column("docq_bullet_point_ratio", pa.array(docq_bullet_point_ratio))
        table = table.append_column("docq_ellipsis_line_ratio", pa.array(docq_ellipsis_line_ratio))
        table = table.append_column("docq_alphabet_word_ratio", pa.array(docq_alphabet_word_ratio))
        table = table.append_column("docq_contain_common_en_words", pa.array(docq_contain_common_en_words))
        table = table.append_column("metakenlm_docq_perplex_score", pa.array(docq_perplex_score))

        if self.ft_lang == "ja":
            table = table.append_column("docq_avg_ja_sentence_len", pa.array(docq_avg_ja_sentence_len))
            table = table.append_column("docq_first_ja_alphabet_pos", pa.array(docq_first_ja_alphabet_pos))

        metadata = {
            "total_docs_count": table.num_rows,
        }

        return [table], metadata


class DocQualityTransformConfiguration(DefaultTableTransformConfiguration):
    """
    Provides support for configuring and using the associated Transform class include
    configuration with CLI args and combining of metadata.
    """

    def __init__(self):
        super().__init__(name="DocQuality", transform_class=DocQualityTransform, runtime_class=DocQualityRuntime)
        self.params = {}
        self.daf = None

    def add_input_params(self, parser: argparse.ArgumentParser) -> None:
        """
        Add Transform-specific arguments to the given  parser.
        This will be included in a dictionary used to initialize the NOOPTransform.
        By convention a common prefix should be used for all transform-specific CLI args
        (e.g, noop_, pii_, etc.)
        """
        parser.add_argument("-f", "--ft_lang", default="en")
        parser.add_argument("-dr", "--drop_column_if_existed", default=True, help="drop columns if existed")

        # Add bdoc_quality-specific arguments to create the DataAccess instance to load the domains.
        self.daf = DataAccessFactory(f"{self.name}_")
        self.daf.add_input_params(parser)

    def apply_input_params(self, args: argparse.Namespace) -> bool:
        """
        Validate and apply the arguments that have been parsed
        :param args: user defined arguments including at least, but perhaps more,
        arguments as defined by add_input_arguments().
        :return: True, if validate pass or False otherwise
        """
        self.params["ft_lang"] = args.ft_lang
        self.params["drop_column_if_existed"] = args.drop_column_if_existed
        # return True
        return self.daf.apply_input_params(args)

    def get_transform_metadata(self) -> dict[str, Any]:
        """
        Provides a default implementation if the user has provided a set of keys to the initializer.
        These keys are used in apply_input_params() to extract our key/values from the global Namespace of args.
        :return:
        """
        return self.params


class DocQualityRuntime(DefaultTableTransformRuntime):

    """
    Provides support for configuring and using the associated Transform class include
    configuration with CLI args and combining of metadata.
    """

    def __init__(self, params: dict[str, Any]):
        super().__init__(params)

    def get_transform_config(
        self, data_access_factory: DataAccessFactory, statistics: ActorHandle, files: list[str]
    ) -> dict[str, Any]:
        """
        Set environment for execution
        :param DocQuality_data_access_factory - data access factory
        :return: dictionary of init params
        """
        from doc_c4_statistics import c4_load_ldnoobw_words
        from perplexity import KenLMModel

        ft_lang = self.params.get("ft_lang")
        bad_word_filepath = f"{BAD_WORD_DIR}{ft_lang}"
        re_pattern = c4_load_ldnoobw_words(ft_lang=ft_lang, file_path=bad_word_filepath)
        strip_accent = True
        klm = KenLMModel.from_pretrained(model_path=MODEL_DIR, language=self.ft_lang, strip_accent=strip_accent)

        drop_column_if_existed = self.params.get("drop_column_if_existed")

        return self.params


if __name__ == "__main__":
    # create launcher
    launcher = TransformLauncher(transform_runtime_config=DocQualityTransformConfiguration())
    # create parameters

    # launch
    launcher.launch()
