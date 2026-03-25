import asyncio
from typing import Tuple, Any
from datasets.arrow_dataset import shutil
from swerex.runtime.abstract import CreateBashSessionRequest, BashAction, Command, WriteFileRequest, \
    CloseBashSessionRequest
from swerex.deployment.docker import DockerDeployment
import os
import uuid
from swerex.deployment.config import DockerDeploymentConfig
from src.agent.constant import DOCKER_MAP_DIR, REPO_MAP_DIR


def extract_git_diff_swerex_container(runtime_config_obj=None):
    from src.agent.runtime_config import RuntimeConfig, RuntimeType
    rc = runtime_config_obj if runtime_config_obj is not None else RuntimeConfig()
    print(rc.look_status_all_config())
    print("Extracting git diff from SWEREX container")
    if not rc.initialized:
        print("ERROR: RuntimeConfig is not initialized");
        return ""
    if int(rc.runtime_type) != int(RuntimeType.SWEREX):
        print(f"ERROR: Expected RuntimeType.SWEREX, got {rc.runtime_type}");
        return ""
    if not rc.swe_rex_deployment:
        print("ERROR: No SWE-REX deployment available");
        return ""

    try:
        swe_rex_runtime = rc.swe_rex_deployment.runtime
        cmd = "cd /testbed && git config core.filemode false && git diff --no-color -U0 --diff-filter=M"
        git_diff_result = asyncio.run(
            swe_rex_runtime.run_in_session(BashAction(command=cmd, check="ignore", timeout=60))
        )

        patch = git_diff_result.output or ""
        return "\n".join(patch.splitlines()) + "\n"

    except Exception as e:
        print(f"ERROR in extract_git_diff_swerex_container: {e}")
        return ""


async def load_swe_instance_for_swerex(instance_id: str, checkout_commit: str | None = None) -> Tuple[
    DockerDeployment, str]:
    repo, name = instance_id.split('__')
    docker_image_name = f'swebench/sweb.eval.x86_64.{repo}_1776_{name}:latest'
    tmp_folder_name = str(uuid.uuid4())[:8]
    docker_map_path = os.path.join(os.path.join(DOCKER_MAP_DIR, instance_id), tmp_folder_name)
    os.makedirs(docker_map_path, exist_ok=True)
    print(f"docker_map_path: {docker_map_path}")
    ######
    docker_args = [
        "-v", f"{docker_map_path}:{docker_map_path}",
        "-w", "/",
    ]

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        deployment = None
        try:
            config = DockerDeploymentConfig(
                image=docker_image_name,
                docker_args=docker_args,
                python_standalone_dir=None,
                startup_timeout=600.0,
            )
            deployment = config.get_deployment()
            await deployment.start()
            break
        except Exception as e:
            last_err = e
            print(f"[load_swe_instance_for_swerex] start failed on attempt {attempt}/{max_retries}: {e}")
            # 新增：清理可能已“唤醒但未就绪”的容器/进程
            if deployment is not None:
                try:
                    await deployment.stop()
                except Exception:
                    pass
            if attempt == max_retries:
                # 最后一次也失败就直接抛出去
                raise
            # 可以稍微 sleep 一下再重试
            await asyncio.sleep(10)
    swe_rex_runtime = deployment.runtime
    try:
        await swe_rex_runtime.create_session(CreateBashSessionRequest())

        if checkout_commit:
            print(await swe_rex_runtime.run_in_session(
                BashAction(command=f"cd /testbed && git checkout {checkout_commit}", check="ignore")))

        print(
            await swe_rex_runtime.run_in_session(
                BashAction(
                    command="git config user.name 'Temp User' && git config user.email 'temp@example.com' && git commit -am 'swe-bench-extra'",
                    check="ignore",
                )
            )
        )
        print(
            await swe_rex_runtime.run_in_session(
                BashAction(command=f"mv /testbed/ {docker_map_path}/")
            )
        )
        await swe_rex_runtime.close_session(CloseBashSessionRequest())
        await swe_rex_runtime.create_session(CreateBashSessionRequest())
        await swe_rex_runtime.run_in_session(BashAction(command=f"cd {docker_map_path}/testbed", check="silent"))
        print(
            await swe_rex_runtime.run_in_session(
                BashAction(command=f"cd {docker_map_path}/testbed && git config core.fileMode false")
            )
        )
        print(
            await swe_rex_runtime.run_in_session(
                BashAction(command=f"chmod -R 777 {docker_map_path}/testbed")
            )
        )
        print(
            await swe_rex_runtime.run_in_session(
                BashAction(command=f"ln -s {docker_map_path}/testbed /testbed")
            )
        )
        print(await swe_rex_runtime.run_in_session(BashAction(command=f"cd {docker_map_path}/testbed")))
        project_path = os.path.join(docker_map_path, "testbed")

        repo_map_path = os.path.join(REPO_MAP_DIR, f"{instance_id}")
        docker_map_repo_path = os.path.join(docker_map_path, "testbed")
        if not os.path.exists(repo_map_path):
            print(f"Copying pristine copy of {instance_id} to {repo_map_path} for wiki")
            shutil.copytree(docker_map_repo_path, repo_map_path)

        print(f"Project path: {project_path}")
        return deployment, project_path
    except Exception:
        try:
            await deployment.stop()
        except Exception:
            pass
        raise

