export interface ProcessingInfo {
  intent?: string
  intent_confidence?: number
  resolved_query?: string
  route?: string
  evidence_confidence?: number
  evidence_passed?: boolean
  fallback_source?: string
  self_check_reason?: string
  decision?: string
  confidence_signals?: {
    top1_score?: number
    valid_count?: number
    margin?: number
    key_clause_hit?: boolean
  }
  retrieved_snapshot?: {
    question: string
    answer: string
    section_path: string
    rerank_score?: number
  }[]
  tools?: { name: string; ok: boolean; arguments: Record<string, string>; result: string }[]
}

export default function ProcessingReport({ info }: { info: ProcessingInfo }) {
  if (!info.resolved_query) return null
  const signals = info.confidence_signals || {}
  const hits = info.retrieved_snapshot || []
  return (
    <div className="processing-report">
      <section>
        <h4>问题理解</h4>
        <p>{info.resolved_query}</p>
        <dl>
          <dt>识别意图</dt>
          <dd>{info.intent || '暂无'}</dd>
          {info.intent_confidence !== undefined && (
            <>
              <dt>意图置信度</dt>
              <dd>{info.intent_confidence.toFixed(2)}</dd>
            </>
          )}
          <dt>处理路径</dt>
          <dd>
            {{
              knowledge: '知识问答',
              business: '业务工具',
              order: '订单处理',
              complaint: '投诉处理',
              fallback: '兜底处理',
              fallback_script: '场景回复',
            }[info.route || ''] ||
              info.route ||
              '暂无'}
          </dd>
        </dl>
      </section>
      {(hits.length > 0 || info.fallback_source) && (
        <section>
          <h4>检索与证据门控</h4>
          <dl>
            <dt>证据置信度</dt>
            <dd>{info.evidence_confidence?.toFixed(4) ?? '暂无'}</dd>
            <dt>门控结果</dt>
            <dd>{info.evidence_passed ? '通过' : '未通过'}</dd>
            {signals.top1_score !== undefined && (
              <>
                <dt>最高重排分数</dt>
                <dd>{signals.top1_score.toFixed(4)}</dd>
              </>
            )}
            {signals.valid_count !== undefined && (
              <>
                <dt>有效候选数</dt>
                <dd>{signals.valid_count}</dd>
              </>
            )}
            {signals.margin !== undefined && (
              <>
                <dt>前两名分差</dt>
                <dd>{signals.margin.toFixed(4)}</dd>
              </>
            )}
            {signals.key_clause_hit !== undefined && (
              <>
                <dt>关键条款命中</dt>
                <dd>{signals.key_clause_hit ? '是' : '否'}</dd>
              </>
            )}
          </dl>
          {info.self_check_reason && (
            <p className="process-rationale">证据自评说明：{info.self_check_reason}</p>
          )}
          {hits.map((hit, index) => (
            <details className="process-evidence" key={`${hit.section_path}-${index}`}>
              <summary>
                候选 {index + 1} · {hit.question}
                <small>重排分数 {hit.rerank_score?.toFixed(4) ?? '未记录'}</small>
              </summary>
              <small>{hit.section_path}</small>
              <p>{hit.answer}</p>
            </details>
          ))}
        </section>
      )}
      {!!info.tools?.length && (
        <section>
          <h4>工具执行结果</h4>
          {info.tools.map((tool, index) => (
            <details className="process-evidence" key={index}>
              <summary>
                {tool.name} · {tool.ok ? '成功' : '失败'}
              </summary>
              {Object.entries(tool.arguments).map(([key, value]) => (
                <p key={key}>
                  {key}：{value}
                </p>
              ))}
              <p>{tool.result}</p>
            </details>
          ))}
        </section>
      )}
      {info.decision && (
        <section>
          <h4>处理决策摘要</h4>
          <p>{info.decision}</p>
        </section>
      )}
    </div>
  )
}
