export interface User {
  id: string
  email: string
  name: string
  role: 'customer' | 'agent'
}
export interface Order {
  order_id: string
  product: string
  product_id: string
  status: string
  amount: number
  created_at: string
  delivered_at: string | null
  tracking_no: string | null
  logistics: { time: string; city: string; text: string }[]
}
export interface Case {
  id: string
  order_id: string
  user_id: string
  reason: string
  description: string
  status: string
  version: number
  created_at: string
  conversation_id: number | null
  order?: Order
  events?: { id: string; action: string; note: string; actor_id: string; created_at: string }[]
}
export interface Citation {
  n: number
  id: number
  section_path: string
  question: string
  answer: string
}
export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
}
export interface Conversation {
  id: number
  title?: string
  preview?: string
  created_at?: string
  status: string
}
export interface Pending {
  type?: string
  kind?: string
  interrupt_id: string
  orders?: Order[]
  preview?: { description?: string; ticket_type?: string }
}
export interface Action {
  type: string
  draft?: { order_id?: string; reason?: string; description?: string; ticket_type?: string }
  orders?: Order[]
}
export interface StreamEvent {
  detail?: Record<string, string | number>
  event?: string
  delta?: string
  message?: string
  conversation_id?: number
  kind?: string
  interrupt_id?: string
  orders?: Order[]
  preview?: Pending['preview']
  items?: Citation[] | Action[]
  name?: string
}
export interface PoolQuestion {
  id: number
  raw_question: string
  source: string
  reason: string | null
  conversation_id: number | null
  created_at: string | null
}
export interface Review {
  id: number
  normalized_question: string
  ai_suggested_answer: string | null
  occurrence_count: number
  review_status: string
  created_at: string | null
  approved_answer?: string | null
  raws?: { raw_question: string; source: string; reason: string; created_at: string }[]
  publication?: { status: string; answer: string; error: string | null } | null
}
export interface SystemStatus {
  model_configured: boolean
  retrieval_configured: boolean
  observability: { provider: string; enabled: boolean; project: string }
}
export interface KbStats {
  total: number | null
  pending: number | null
  done: number | null
  by_content_type: Record<string, number>
  key_clause: number | null
}
export interface KbMilvus {
  online: boolean
  count: number | null
  collection: string
  detail?: string
}
export interface KbFeatures {
  sections: number
  table_split: boolean
  overlap: boolean
  multi_piece_sections: string[]
}
export interface KbSource {
  file: string
  content_type: string
  present: boolean
  path: string
  chars?: number
  lines?: number
  mtime?: string
  chunks?: number
  key_clause?: number
  features?: KbFeatures
}
export interface KbChunk {
  id?: number
  seq?: number
  questions: string
  answer: string
  section_path?: string
  category?: string
  content_type?: string
  status?: string
  is_key_clause?: boolean
  is_table?: boolean
  duplicate?: boolean | null
  created_at?: string
  chars?: number
}
export interface KbStagingStats {
  counts: Record<string, number>
  total: number
  batches: number
  latest_batch: string | null
}
export interface KbOverview {
  chunks: KbStats
  recent: KbChunk[]
  staging: KbStagingStats | null
  db_error: string | null
  milvus: KbMilvus
  consistent: boolean | null
  sources: KbSource[]
  content_types: { key: string; desc: string }[]
}
export interface KbPreview {
  source: string
  content_type: string
  chars: number
  total: number
  duplicates: number
  key_clause: number
  features: KbFeatures
  chunks: KbChunk[]
  dedup_known: boolean
}
export interface KbIngest {
  content_type: string
  chunks: number
  inserted: number
  skipped: number
  skipped_samples: { questions: string; answer: string }[]
  vectorized: number | null
  milvus: KbMilvus
  chunk_stats: KbStats
}
export interface KbHit {
  id: number | null
  question: string
  answer: string
  score: number | null
  rerank_score: number | null
  section_path: string | null
  content_type: string | null
  category: string | null
}
export interface KbStagingRow {
  id: number
  batch_no: string
  source_ref: string
  question: string
  answer: string
}
export interface KbStaging {
  stats: KbStagingStats
  rows: Record<string, KbStagingRow[]>
}
