#!/usr/bin/env cwl-runner
# This file was autogenerated using the Workflow Inference Compiler, version 0+unknown
# https://github.com/PolusAI/workflow-inference-compiler
steps:
- id: helloworld__step__1__echo
  in:
    message:
      source: helloworld__step__1__echo___message
  run: helloworld__step__1__echo/echo.cwl
  out:
  - stdout
cwlVersion: v1.2
class: Workflow
$namespaces:
  edam: https://edamontology.org/
$schemas:
- https://raw.githubusercontent.com/edamontology/edamontology/master/EDAM_dev.owl
inputs:
  helloworld__step__1__echo___message:
    type: string
outputs:
  helloworld__step__1__echo___stdout:
    type: File
    outputSource: helloworld__step__1__echo/stdout