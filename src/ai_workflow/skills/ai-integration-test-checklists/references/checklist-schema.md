# Checklist Schema

## Scope

写明 repo、service、接口、模块路径、相关数据或外部系统。

## Evidence Map

每条 evidence 使用稳定编号，例如 `E1`、`E2`。记录来源、文件或描述、关键事实。

## Checklist Items

每个 checklist item 必须指向 evidence，并包含：

- id
- title
- evidence
- setup
- action
- expected result
- priority

## Gap Analysis

列出当前无法覆盖的缺口、缺少的环境、缺少的 mock、未确认的业务规则和残余风险。

## Verification Commands

列出可执行命令。没有命令时，说明缺少什么 repository adapter 或环境条件。
