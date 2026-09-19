# Convergence

## Failure classes

- `implementation bug`：实现不满足需求或契约。
- `test asset bug`：case、fixture、mock、初始化数据或断言自身错误。
- `environment issue`：依赖服务、权限、网络、账号、环境变量或测试环境缺失。
- `mock/fixture drift`：mock 或 fixture 与真实契约漂移。

## Rerun evidence

每次 rerun 必须记录：

- command argv
- working directory
- exit status
- bounded log excerpt
- changed files
- remaining failures

## Prohibited shortcuts

Do not update expected output to match broken behavior. 不要删除失败 case，不要把环境失败伪装成实现通过。
