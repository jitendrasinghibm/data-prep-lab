# (C) Copyright IBM Corp. 2024.
# Licensed under the Apache License, Version 2.0 (the “License”);
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#  http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an “AS IS” BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
################################################################################

import sys
from typing import Any

from data_processing.data_access import DataAccess, DataAccessFactory
from kfp_support.workflow_support.utils import KFPUtils, RayRemoteJobs


def execute_ray_jobs(
    name: str,  # name of Ray cluster
    d_access: DataAccess,  # data access
    additional_params: dict[str, Any],
    e_params: dict[str, Any],
    exec_script_name: str,
    server_url: str,
) -> None:
    """
    Execute Ray job on a cluster periodically printing execution log. Completes when Ray job completes
    (succeeds or fails)
    :param name: cluster name
    :param d_access: data access class
    :param additional_params: additional parameters for the job
    :param e_params: job execution parameters (specific for a specific transform,
                        generated by the transform workflow)
    :param exec_script_name: script to run (has to be present in the image)
    :param server_url: API server url
    :return: None
    """
    # get current namespace
    ns = KFPUtils.get_namespace()
    if ns == "":
        print(f"Failed to get namespace")
        sys.exit(1)
    # submit job
    remote_jobs = RayRemoteJobs(
        server_url=server_url,
        http_retries=additional_params.get("http_retries", 5),
        wait_interval=additional_params.get("wait_interval", 2),
    )
    status, error, submission = remote_jobs.submit_job(
        name=name, namespace=ns, request=e_params, executor=exec_script_name
    )
    if status != 200:
        print(f"Failed to submit job - status: {status}, error: {error}, submission id {submission}")
        exit(1)

    print(f"submit job - status: {status}, error: {error}, submission id {submission}")
    # print execution log
    remote_jobs.follow_execution(
        name=name,
        namespace=ns,
        submission_id=submission,
        data_access=d_access,
        print_timeout=additional_params.get("wait_print_tmout", 120),
        job_ready_timeout=additional_params.get("wait_job_ready_tmout", 600),
    )


if __name__ == "__main__":
    import argparse

    """
    This implementation is not completely generic. It is based on the assumption
    that there is 1 additional data access and it is S3 base. A typical example for such
    use case is usage of 2 S3 buckets with different access credentials -
    one for the data access and one for the additional data, for example, config files, models, etc.
    """
    parser = argparse.ArgumentParser(description="Execute Ray job operation")
    parser.add_argument("--ray_name", type=str, default="")
    parser.add_argument("--run_id", type=str, default="")
    parser.add_argument("--additional_params", type=str, default="{}")
    parser.add_argument("--server_url", type=str, default="")
    parser.add_argument("--prefix", type=str, default="")
    # The component converts the dictionary to json string
    parser.add_argument("--exec_params", type=str, default="{}")
    parser.add_argument("--exec_script_name", default="transformer_launcher.py", type=str)

    args = parser.parse_args()
    cluster_name = KFPUtils.runtime_name(
        ray_name=args.ray_name,
        run_id=args.run_id,
    )
    # convert exec params to dictionary
    exec_params = KFPUtils.load_from_json(args.exec_params)
    # convert s3 config to proper dictionary to use for data access factory
    s3_config = exec_params.get("data_s3_config", "None")
    if s3_config == "None" or s3_config == "":
        s3_config_dict = None
    else:
        s3_config_dict = KFPUtils.load_from_json(s3_config.replace("'", '"'))
    # get and build S3 credentials
    access_key, secret_key, url = KFPUtils.credentials()
    # Create data access factory and data access
    data_factory = DataAccessFactory()
    data_factory.apply_input_params(
        args={
            "data_s3_config": s3_config_dict,
            "data_s3_cred": {"access_key": access_key, "secret_key": secret_key, "url": url},
        }
    )
    data_access = data_factory.create_data_access()
    # extra credentials
    prefix = args.prefix
    extra_access_key, extra_secret_key, extra_url = KFPUtils.credentials(
        access_key=f"{prefix}_S3_KEY", secret_key=f"{prefix}_S3_SECRET", endpoint=f"{prefix}_ENDPOINT"
    )
    # enhance exec params
    exec_params["data_s3_cred"] = (
        "{'access_key': '" + access_key + "', 'secret_key': '" + secret_key + "', 'url': '" + url + "'}"
    )
    exec_params[f"{prefix}_s3_cred"] = (
        "{'access_key': '"
        + extra_access_key
        + "', 'secret_key': '"
        + extra_secret_key
        + "', 'url': '"
        + extra_url
        + "'}"
    )
    # Execute Ray jobs
    execute_ray_jobs(
        name=cluster_name,
        d_access=data_access,
        additional_params=KFPUtils.load_from_json(args.additional_params),
        e_params=exec_params,
        exec_script_name=args.exec_script_name,
        server_url=args.server_url,
    )
