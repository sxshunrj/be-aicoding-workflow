# Repository Adapter

Integration test generator 只使用 `.ai-workflow.yaml` 中声明的 repository adapter。

## Fields

- `source_paths`：生产代码或接口契约的路径模式，用于定位被测对象。
- `test_paths`：已有测试资产路径模式，用于复用 fixture、mock 和 case 风格。
- `generated_test_destinations`：允许写入新生成测试的目录。
- `report_paths`：测试报告或诊断输出路径。
- `commands.integration_test`：运行 integration-test 的 argv 命令。
- `protected_paths`：禁止写入路径。

## Behavior

如果 `generated_test_destinations` 为空，停止并请求用户补充 adapter。若 `commands.integration_test` 缺失，只能生成文件并报告无法执行验证命令。
