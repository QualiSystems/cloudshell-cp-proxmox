import os
import subprocess

current_dir = os.path.dirname(os.path.abspath(__file__))
shell_dir = os.path.abspath(
    os.path.join(
        current_dir,
        os.pardir,
        "\Proxmox-Cloud-Provide-Shell-2G"
    )
)
with open(os.path.join(current_dir, "version.txt"), "r") as f:
    version = f.read()
    # new_version = f.read()

version = version.strip().rsplit(".", maxsplit=1)
new_version = ".".join((version[0], (str(int(version[-1]) + 1))))
with open(os.path.join(current_dir, "version.txt"), "w") as f:
    f.write(new_version + "\n")
build = subprocess.check_output(
    "py -3 .\setup.py bdist_wheel",
    stderr=subprocess.STDOUT,
    shell=True,
    cwd=current_dir
)
if not os.path.exists(
        os.path.join(
            current_dir,
            f".\dist\cloudshell_cp_proxmox-{new_version}-py3-none-any.whl"
        )
):
    Exception("Build failed")
upload = subprocess.check_output(
    f"twine upload --repository-url http://localhost:8036/ "
         f".\dist\cloudshell_cp_proxmox-{new_version}-py3-none-any.whl -u pypiadmin "
         f"-p pypiadmin",
    stderr=subprocess.STDOUT,
    shell=True,
    cwd=current_dir
)
shellfoundry = subprocess.check_output("shellfoundry install",
                                      stderr=subprocess.STDOUT, shell=True,
                                       cwd=shell_dir)
