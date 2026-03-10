export type AgentStatus = 'idle' | 'working' | 'thinking' | 'communicating';
export type AgentRole = string;
export type TaskStatus = 'todo' | 'in_progress' | 'done' | 'cancelled';
export type MessageType = 'chat' | 'agent' | 'system' | 'error' | 'deliverable';

export interface SkillOption {
  id: string;
  display_name: string;
  description: string;
  emoji?: string;
  compatible_roles?: string[];
}

export interface RoleOption {
  id: string;
  display_name: string;
  emoji: string;
  description: string;
  core_tool_ids: string[];
  default_skills: string[];
  system_prompt: string;
}

export interface AgentMemory {
  short_term: Array<{ role: string; content: string; timestamp: string }>;
  long_term_summary: string;
  task_history: string[];
}

export interface Agent {
  id: string;
  name: string;
  role: AgentRole;
  avatar_index: number;
  skills: string[];
  system_prompt: string;
  workstation_id: string;
  status: AgentStatus;
  memory: AgentMemory;
  model: string;
  created_at: string;
}

export interface SubTask {
  id: string;
  title: string;
  description: string;
  assigned_to: string | null;
  status: TaskStatus;
  output?: string;
  depends_on?: string[];
  read_from?: string[];
}

// Scratchpad entry
export interface ScratchpadEntry {
  task_id: string;
  key: string;
  content: string;
  author_id: string;
  author_name: string;
}

export interface Task {
  id: string;
  title: string;
  description: string;
  status: TaskStatus;
  assigned_to: string[];
  subtasks: SubTask[];
  scratchpad?: ScratchpadEntry[];
  created_by: string;
  output?: string;
  progress?: number;
  pm_model?: string;
  pm_api_key?: string;
  schedule?: string | null;
  next_run_at?: string | null;
  last_run_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface InteractionLog {
  id: string;
  from_id: string;
  to_id: string;
  content: string;
  type: MessageType;
  timestamp: Date;
}

export interface WorkstationInfo {
  id: string;
  x: number;
  y: number;
  agentId?: string;
}

export interface LLMModel {
  id: string;
  name: string;
  recommended?: boolean;
}

export interface LLMProvider {
  id: string;
  name: string;
  api_base: string;
  models: LLMModel[];
}

export interface ActivityEvent {
  id: string;
  type: 'pm' | 'agent' | 'system' | 'status' | 'subtask';
  content: string;
  agent_name?: string;
  timestamp: Date;
}

export interface TaskMetrics {
  task_id: string;
  total_duration_s: number;
  subtask_count: number;
  tool_call_count: number;
  tool_call_distribution: Record<string, number>;
  reflection_count: number;
  self_critique_count: number;
  rework_count: number;
  replan_count: number;
  llm_errors: number;
  subtask_durations: Record<string, number>;
}

// WebSocket event types
export type WSEventType =
  | 'init'
  | 'agent:created'
  | 'agent:removed'
  | 'agent:status'
  | 'agent:message'
  | 'task:created'
  | 'task:removed'
  | 'task:update'
  | 'task:subtask'
  | 'task:assigned'
  | 'task:metrics'
  | 'system:log'
  | 'scratchpad:update'
  | 'scratchpad:clear'
  | 'subtask:stream'
  | 'subtask:stream_end';

export interface WSMessage {
  event: WSEventType;
  data: Record<string, unknown>;
}
