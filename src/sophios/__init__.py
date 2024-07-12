
from . import _version
__version__ = _version.get_versions()['version']

# Well, not THIS file.
auto_gen_header = f"""# This file was autogenerated using the Workflow Inference Compiler, version {__version__}
# https://github.com/PolusAI/workflow-inference-compiler\n"""