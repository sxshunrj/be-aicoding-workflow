import { useState } from 'react'

export const GLOSSARY: Record<string, { short: string; detail: string }> = {
  run: {
    short: 'Run = 一次任务执行',
    detail: '对"完成某个需求"的完整跟踪：从需求提交，到四个阶段执行，到最终完成/中止。每个 Run 有唯一 ID（RUN-日期-时间-随机码）。',
  },
  spec: { short: 'spec = 需求规格阶段', detail: 'agent 先把你的需求写成结构化的规格说明（要做什么、不做什么、验收标准），作为后续所有工作的依据。' },
  plan: { short: 'plan = 实施计划阶段', detail: 'agent 拆解实施计划：改哪些文件、分几个子任务、怎么验证。' },
  implement: { short: 'implement = 实现阶段', detail: 'agent 按计划真正写代码的阶段，产出实现记录。' },
  verify: { short: 'verify = 验证阶段', detail: '跑构建、单元测试、集成测试、代码审查，确认改动可靠。verify 有节点时才会执行。' },
  profile: { short: 'profile = 流程模板', detail: 'full = 完整四阶段（spec→plan→implement→verify）；grill = 三阶段（plan→implement→verify，PRD 驱动，适合需求已经写好的场景）。' },
  'review gate': { short: 'review gate = 人工审批关卡', detail: '流程在某些节点会暂停，生成一个"待审批"卡片：agent 说明做了什么、建议怎么继续（是否重跑某些节点）。你「接受」流程才继续，「驳回」会让 run 停下等待处理。' },
  digest: { short: 'digest = 内容指纹', detail: '对 gate/知识条目内容的 SHA-256 哈希。审批时用来确认"你批的就是你看到的"——若内容在你审批前被改动，digest 不匹配，操作会被拒绝（乐观锁）。' },
  rerun: { short: 'rerun = 重跑节点', detail: '某个阶段做得不好时，可以标记它"重跑"并给理由；恢复 run 后 agent 会重做该节点而不是从头来过。' },
  attempt: { short: 'attempt = 第几次尝试', detail: '一个节点可以多次尝试（比如测试失败后重跑），attempt 记录是第几轮。' },
  'knowledge packet': { short: '知识包 = 阶段参考资料', detail: '阶段开始时系统从知识库里检索相关经验，打包给 agent 参考。知识库越丰富，包越有用。' },
  reflection: { short: 'reflection = 结算反思', detail: 'run 结束后 agent 做复盘：这次学到什么？有什么值得沉淀的经验？产出候选知识等你批准入库。' },
  candidate: { short: 'candidate = 候选知识', detail: 'agent 提交的经验条目，未经你批准。在「知识治理」页可以批准（进入知识库）、驳回或归档。' },
  approved: { short: 'approved = 已批准知识', detail: '已进入知识库的经验，后续 run 的知识包会自动检索它们。' },
  'source revision': { short: 'source revision = 起点版本', detail: '这个 run 从 git 的哪个提交开始做，方便回溯和对比改动。' },
}

export function Term({ children, term }: { children?: React.ReactNode; term: keyof typeof GLOSSARY | string }) {
  const entry = GLOSSARY[term]
  const [open, setOpen] = useState(false)
  if (!entry) return <>{children ?? term}</>
  return (
    <span
      className="term"
      onClick={(event) => {
        event.stopPropagation()
        setOpen((value) => !value)
      }}
      title="点击查看解释"
    >
      {children ?? term}
      {open && (
        <span className="term-pop" onClick={(event) => event.stopPropagation()}>
          <b>{entry.short}</b>
          <span>{entry.detail}</span>
        </span>
      )}
    </span>
  )
}
