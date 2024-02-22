import copy
import logging
import glob
import os
from pathlib import Path
import re
from typing import Dict

import cwltool.load_tool
import yaml

from . import input_output as io
from .python_cwl_adapter import import_python_file
from .wic_types import Cwl, NodeData, RoseTree, StepId, Tool, Tools


# Filter out the "... previously defined" id uniqueness validation warnings
# from line 1162 of ref_resolver.py in the schema_salad library.
# TODO: Figure out if there is a problem with our autogenerated CWL.
class NoPreviouslyDefinedFilter(logging.Filter):
    # pylint:disable=too-few-public-methods
    def filter(self, record: logging.LogRecord) -> bool:
        return not record.getMessage().endswith('previously defined')


class NoResolvedFilter(logging.Filter):
    # pylint:disable=too-few-public-methods
    def filter(self, record: logging.LogRecord) -> bool:
        m = re.match(r"Resolved '.*' to '.*'", record.getMessage())
        return not bool(m)  # (True if m else False)


def logging_filters() -> None:
    logger_salad = logging.getLogger("salad")
    logger_salad.addFilter(NoPreviouslyDefinedFilter())
    logger_cwltool = logging.getLogger("cwltool")
    logger_cwltool.addFilter(NoResolvedFilter())


def validate_cwl(cwl_path_str: str, skip_schemas: bool) -> None:
    """This is the body of cwltool.load_tool.load_tool but exposes skip_schemas for performance.
    Skipping significantly improves initial validation performance, but this is not always desired.
    See https://github.com/common-workflow-language/cwltool/issues/623

    Args:
        cwl_path_str (str): The path to the CWL file.
        skip_schemas (bool): Skips processing $schemas tags.
    """
    # NOTE: This uses NoResolvedFilter to suppress the info messages to stdout.
    loading_context, workflowobj, uri = cwltool.load_tool.fetch_document(cwl_path_str)
    # NOTE: There has been a breaking change in the API for skip_schemas.
    # TODO: re-enable skip_schemas while satisfying mypy
    # loading_context.skip_schemas = skip_schemas
    loading_context, uri = cwltool.load_tool.resolve_and_validate_document(
        loading_context, workflowobj, uri, preprocess_only=False  # , skip_schemas=skip_schemas
    )
    # NOTE: Although resolve_and_validate_document does some validation,
    # some additional validation is done in make_tool, i.e.
    # resolve_and_validate_document does not in fact throw an exception for
    # some invalid CWL files, but make_tool does!
    process_ = cwltool.load_tool.make_tool(uri, loading_context)
    # return process_ # ignore process_ for now


def get_tools_cwl(homedir: str, validate_plugins: bool = False,
                  skip_schemas: bool = False, quiet: bool = False) -> Tools:
    """Uses glob() to find all of the CWL CommandLineTool definition files within any subdirectory of cwl_dir

    Args:
        homedir (str): The users home directory
        cwl_dirs_file (Path): The subdirectories in which to search for CWL CommandLineTools
        validate_plugins (bool, optional): Performs validation on all CWL CommandLiineTools. Defaults to False.
        skip_schemas (bool, optional): Skips processing $schemas tags. Defaults to False.
        quiet (bool, optional): Determines whether it captures stdout or stderr. Defaults to False.

    Returns:
        Tools: The CWL CommandLineTool definitions found using glob()
    """
    io.copy_config_files(homedir)
    # Load ALL of the tools.
    tools_cwl: Tools = {}
    cwl_dirs_file = Path(homedir) / 'wic' / 'cwl_dirs.txt'
    cwl_dirs = io.read_lines_pairs(cwl_dirs_file)
    for plugin_ns, cwl_dir in cwl_dirs:
        # "PurePath.relative_to() requires self to be the subpath of the argument, but os.path.relpath() does not."
        # See https://docs.python.org/3/library/pathlib.html#id4 and
        # See https://stackoverflow.com/questions/67452690/pathlib-path-relative-to-vs-os-path-relpath
        pattern_cwl = str(Path(cwl_dir) / '**/*.cwl')
        # print(pattern_cwl)
        cwl_paths = glob.glob(pattern_cwl, recursive=True)
        Path('autogenerated/schemas/tools/').mkdir(parents=True, exist_ok=True)
        if len(cwl_paths) == 0:
            print(f'Warning! No cwl files found in {cwl_dir}.\nCheck {cwl_dirs_file.absolute()}')
            print('This almost certainly means you are not in the correct directory.')

        for cwl_path_str in cwl_paths:
            if 'biobb_md' in cwl_path_str:
                continue  # biobb_md is deprecated (in favor of biobb_gromacs)
            # print(cwl_path)
            with open(cwl_path_str, mode='r', encoding='utf-8') as f:
                tool: Cwl = yaml.safe_load(f.read())
            stem = Path(cwl_path_str).stem
            # print(stem)

            if validate_plugins:
                validate_cwl(cwl_path_str, skip_schemas)
            if quiet:
                # Capture stdout and stderr
                if not 'stdout' in tool:
                    tool.update({'stdout': f'{stem}.out'})
                if not 'stderr' in tool:
                    tool.update({'stderr': f'{stem}.err'})
            cwl_path_abs = os.path.abspath(cwl_path_str)
            tools_cwl[StepId(stem, plugin_ns)] = Tool(cwl_path_abs, tool)
            # print(tool)
            # utils_graphs.make_tool_dag(stem, (cwl_path_str, tool))
    return tools_cwl


def dockerPull_append_noentrypoint(cwl: Cwl) -> Cwl:
    """Appends -noentrypoint to the dockerPull version tag (if any)

    Args:
        cwl (Cwl): A CWL CommandLineTool

    Returns:
        Cwl: A CWL CommandLineTool, with -noentrypoint appended to the dockerPull version tag (if any)
    """
    docker_image: str = cwl.get('requirements', {}).get('DockerRequirement', {}).get('dockerPull', '')
    if docker_image:
        print('docker_image', docker_image)
    if ':' in docker_image:
        repo, tag = docker_image.split(':')
    else:
        repo, tag = docker_image, 'latest'
    if repo and tag and not tag.endswith('-noentrypoint'):
        print('repo, tag', repo, tag)
        image_noentrypoint = repo + ':' + tag + '-noentrypoint'
        cwl_noentrypoint = copy.deepcopy(cwl)
        cwl_noentrypoint['requirements']['DockerRequirement']['dockerPull'] = image_noentrypoint
        return cwl_noentrypoint
    else:
        return cwl


def dockerPull_append_noentrypoint_tools(tools: Tools) -> Tools:
    """Appends -noentrypoint to the dockerPull version tag for every tool in tools.

    Args:
        tools (Tools): The CWL CommandLineTool definitions found using get_tools_cwl()

    Returns:
        Tools: tools with -noentrypoint appended to all of the dockerPull version tags.
    """
    return {stepid: Tool(tool.run_path, dockerPull_append_noentrypoint(tool.cwl))
            for stepid, tool in tools.items()}


def dockerPull_append_noentrypoint_rosetree(rose_tree: RoseTree) -> RoseTree:
    """Appends -noentrypoint to the dockerPull version tag for every CWL CommandLineTool

    Args:
        rose_tree (RoseTree): The RoseTree returned from compile_workflow(...).rose_tree

    Returns:
        RoseTree: rose_tree with -noentrypoint appended to the dockerPull version tag for every CWL CommandLineTool
    """
    n_d: NodeData = rose_tree.data
    # NOTE: Since only class: CommandLineTool should have dockerPull tags,
    # this should be the identity function on class: Workflow.
    compiled_cwl_noent = dockerPull_append_noentrypoint(n_d.compiled_cwl)

    sub_trees_noent = [dockerPull_append_noentrypoint_rosetree(sub_rose_tree) for sub_rose_tree in rose_tree.sub_trees]
    node_data_noent = NodeData(n_d.namespaces, n_d.name, n_d.yml, compiled_cwl_noent, n_d.workflow_inputs_file,
                               n_d.explicit_edge_defs, n_d.explicit_edge_calls, n_d.graph, n_d.inputs_workflow,
                               n_d.step_name_1)
    return RoseTree(node_data_noent, sub_trees_noent)


def get_workflow_paths(homedir: str, extension: str) -> Dict[str, Dict[str, Path]]:
    """Uses glob() to recursively find all of the yml workflow definition files
    within any subdirectory of each yml_dir in yml_dirs_file.
    NOTE: This function assumes all yml files found are workflow definition files,
    so do not mix regular yml files and workflow files in the same root directory.
    Moreover, each yml_dir should be disjoint; do not use both '.' and './subdir'!

    Args:
        homedir (str): The users home directory
        extension (str): The filename extension (either 'yml' or 'py')

    Returns:
        Dict[str, Dict[str, Path]]: A dict containing the filepath stem and filepath of each yml file
    """
    io.copy_config_files(homedir)
    yml_dirs_file = Path(homedir) / 'wic' / 'yml_dirs.txt'
    yml_dirs = io.read_lines_pairs(yml_dirs_file)
    # Glob all of the yml files too, so we don't have to deal with relative paths.
    yml_paths_all: Dict[str, Dict[str, Path]] = {}
    for yml_namespace, yml_dir in yml_dirs:
        # "PurePath.relative_to() requires self to be the subpath of the argument, but os.path.relpath() does not."
        # See https://docs.python.org/3/library/pathlib.html#id4 and
        # See https://stackoverflow.com/questions/67452690/pathlib-path-relative-to-vs-os-path-relpath
        pattern_yml = str(Path(yml_dir) / f'**/*.{extension}')
        yml_paths_sorted = sorted(glob.glob(pattern_yml, recursive=True), key=len, reverse=True)
        Path('autogenerated/schemas/workflows/').mkdir(parents=True, exist_ok=True)
        if len(yml_paths_sorted) == 0:
            print(f'Warning! No {extension} files found in {yml_dir}.\nCheck {yml_dirs_file.absolute()}')
            print('This almost certainly means you are not in the correct directory.')
        yml_paths = {}
        for yml_path_str in yml_paths_sorted:
            # Exclude our autogenerated inputs files
            if '_inputs' not in yml_path_str:
                yml_path = Path(yml_path_str)
                yml_path_abs = os.path.abspath(yml_path_str)
                yml_paths[yml_path.stem] = Path(yml_path_abs)
        # Check for existing entry (so we can split a single
        # namespace across multiple lines in yml_dirs.txt)
        ns_dict = yml_paths_all.get(yml_namespace, {})
        yml_paths_all[yml_namespace] = {**ns_dict, **yml_paths}

    return yml_paths_all


def get_yml_paths(homedir: str) -> Dict[str, Dict[str, Path]]:
    return get_workflow_paths(homedir, 'yml')


def get_py_paths(homedir: str) -> Dict[str, Dict[str, Path]]:
    return get_workflow_paths(homedir, 'py')


def blindly_execute_python_workflows() -> None:
    """This function imports (read: blindly executes) all python files in yml_dirs.txt
       The python files are assumed to build a wic.api.pythonapi.Workflow object and
       call the .compile() method, which has the desired side effect of writing a yml file to disk.
       The python files should NOT call the .run() method!
       (from any code path that is automatically executed on import)
    """
    # I hope u like Remote Code Execution vulnerabilities!
    # See https://en.wikipedia.org/wiki/Arithmetical_hierarchy
    paths = get_py_paths(str(Path().home()))
    paths_tuples = [(path_str, path)
                    for namespace, paths_dict in paths.items()
                    for path_str, path in paths_dict.items()]
    for path_str, path in paths_tuples:
        # NOTE: Use anything (unique?) for the python_module_name.
        try:
            module = import_python_file(path_str, path)
        except Exception as e:
            print(f'Could not import python file {path}')
            print(e)
            # TODO: Determine how to handle import failures
        # NOTE: We could require all python API files to define a function, say
        # def workflow(...) -> Workflow
        # and then we could programmatically call it here:
        # retval: Workflow = module.workflow(**args)
        # which would allow us to programmatically call Workflow methods:
        # retval.compile()  # hopefully retval is actually a Workflow object!
        # But since this is python (i.e. not Haskell) that in no way eliminates
        # the above security considerations.
        # So for now let's keep it simple and assume .compile() has been called.
