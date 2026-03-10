import { create } from 'zustand';
import type { Agent, Task, InteractionLog, AgentStatus, SubTask, ScratchpadEntry, ActivityEvent, TaskMetrics } from '../types';

type WsSendFn = (event: string, data: Record<string, unknown>) => void;

interface AppState {
  // Data
  agents: Agent[];
  tasks: Task[];
  logs: InteractionLog[];
  scratchpadEntries: ScratchpadEntry[];
  activityFeed: ActivityEvent[];
  taskMetrics: Record<string, TaskMetrics>;

  // UI State
  selectedWorkstationId: string | null;
  selectedAgentId: string | null;
  selectedTaskId: string | null;
  showCreateAgentModal: boolean;

  // Streaming state
  streamingSubtaskId: string | null;
  streamingContent: string;

  // Task dashboard UI state
  showTaskDashboard: boolean;
  expandedTaskId: string | null;
  selectedSubtaskId: string | null;

  // WebSocket
  wsConnected: boolean;
  wsSend: WsSendFn | null;

  // Actions — Agents
  setAgents: (agents: Agent[]) => void;
  addAgent: (agent: Agent) => void;
  removeAgent: (agentId: string) => void;
  updateAgentStatus: (agentId: string, status: AgentStatus) => void;
  updateAgent: (agentId: string, updates: Partial<Agent>) => void;

  // Actions — Tasks
  setTasks: (tasks: Task[]) => void;
  addTask: (task: Task) => void;
  removeTask: (taskId: string) => void;
  updateTask: (taskId: string, updates: Partial<Task>) => void;
  updateSubtask: (taskId: string, subtaskId: string, updates: Partial<SubTask>) => void;
  addSubtask: (taskId: string, subtask: SubTask) => void;

  // Actions — Activity Feed
  addActivity: (event: Omit<ActivityEvent, 'id'>) => void;

  // Actions — Metrics
  setTaskMetrics: (taskId: string, metrics: TaskMetrics) => void;

  // Actions — Scratchpad
  addScratchpadEntry: (entry: ScratchpadEntry) => void;
  clearScratchpadForTask: (taskId: string) => void;
  clearScratchpad: () => void;

  // Actions — Logs
  addLog: (log: Omit<InteractionLog, 'id'> & { timestamp?: Date }) => void;
  addLogs: (logs: Array<Omit<InteractionLog, 'id'> & { timestamp?: Date }>) => void;

  // Actions — UI
  setSelectedWorkstation: (id: string | null) => void;
  setSelectedAgent: (id: string | null) => void;
  setSelectedTask: (id: string | null) => void;
  openCreateAgentModal: (workstationId?: string) => void;
  closeCreateAgentModal: () => void;
  setWsConnected: (connected: boolean) => void;
  setWsSend: (fn: WsSendFn | null) => void;

  // Actions — Streaming
  setStreamingSubtask: (subtaskId: string | null) => void;
  appendStreamingContent: (chunk: string) => void;
  clearStreamingContent: () => void;

  // Actions — Task Dashboard
  setShowTaskDashboard: (show: boolean) => void;
  toggleTaskDashboard: () => void;
  setExpandedTask: (id: string | null) => void;
  setSelectedSubtask: (id: string | null) => void;
}

let logIdCounter = 0;
let actIdCounter = 0;

export const useStore = create<AppState>((set, get) => ({
  // Initial state
  agents: [],
  tasks: [],
  logs: [],
  scratchpadEntries: [],
  activityFeed: [],
  taskMetrics: {},
  selectedWorkstationId: null,
  selectedAgentId: null,
  selectedTaskId: null,
  showCreateAgentModal: false,
  streamingSubtaskId: null,
  streamingContent: '',
  showTaskDashboard: false,
  expandedTaskId: null,
  selectedSubtaskId: null,
  wsConnected: false,
  wsSend: null,

  // Agent actions
  setAgents: (agents) => set({ agents }),
  addAgent: (agent) =>
    set((state) => ({
      agents: [...state.agents.filter((a) => a.id !== agent.id), agent],
    })),
  removeAgent: (agentId) =>
    set((state) => ({
      agents: state.agents.filter((a) => a.id !== agentId),
    })),
  updateAgentStatus: (agentId, status) =>
    set((state) => ({
      agents: state.agents.map((a) =>
        a.id === agentId ? { ...a, status } : a
      ),
    })),
  updateAgent: (agentId, updates) =>
    set((state) => ({
      agents: state.agents.map((a) =>
        a.id === agentId ? { ...a, ...updates } : a
      ),
    })),

  // Task actions
  setTasks: (tasks) => set({ tasks }),
  addTask: (task) =>
    set((state) => ({
      tasks: [...state.tasks.filter((t) => t.id !== task.id), task],
    })),
  removeTask: (taskId) =>
    set((state) => ({
      tasks: state.tasks.filter((t) => t.id !== taskId),
    })),
  updateTask: (taskId, updates) =>
    set((state) => ({
      tasks: state.tasks.map((t) =>
        t.id === taskId ? { ...t, ...updates } : t
      ),
    })),
  updateSubtask: (taskId, subtaskId, updates) =>
    set((state) => ({
      tasks: state.tasks.map((t) =>
        t.id === taskId
          ? {
              ...t,
              subtasks: t.subtasks.map((st) =>
                st.id === subtaskId ? { ...st, ...updates } : st
              ),
            }
          : t
      ),
    })),
  addSubtask: (taskId, subtask) =>
    set((state) => ({
      tasks: state.tasks.map((t) =>
        t.id === taskId
          ? {
              ...t,
              subtasks: [...t.subtasks.filter((s) => s.id !== subtask.id), subtask],
            }
          : t
      ),
    })),

  // Activity Feed actions
  addActivity: (event) =>
    set((state) => ({
      activityFeed: [
        ...state.activityFeed.slice(-99),
        { ...event, id: `act-${++actIdCounter}` },
      ],
    })),

  // Metrics actions
  setTaskMetrics: (taskId, metrics) =>
    set((state) => ({
      taskMetrics: { ...state.taskMetrics, [taskId]: metrics },
    })),

  // Scratchpad actions
  addScratchpadEntry: (entry) =>
    set((state) => ({
      scratchpadEntries: [
        ...state.scratchpadEntries.filter((e) => e.key !== entry.key),
        entry,
      ],
    })),
  clearScratchpadForTask: (taskId) =>
    set((state) => ({
      scratchpadEntries: state.scratchpadEntries.filter((e) => e.task_id !== taskId),
    })),
  clearScratchpad: () => set({ scratchpadEntries: [] }),

  // Log actions
  addLog: (log) =>
    set((state) => ({
      logs: [
        ...state.logs.slice(-199),  // Keep last 200 logs
        { ...log, id: `log-${++logIdCounter}`, timestamp: log.timestamp ?? new Date() },
      ],
    })),
  addLogs: (newLogs) =>
    set((state) => {
      const entries = newLogs.map((log) => ({
        ...log,
        id: `log-${++logIdCounter}`,
        timestamp: log.timestamp ?? new Date(),
      }));
      const merged = [...state.logs, ...entries]
        .sort((a, b) => a.timestamp.getTime() - b.timestamp.getTime())
        .slice(-200);
      return { logs: merged };
    }),

  // UI actions
  setSelectedWorkstation: (id) => set({ selectedWorkstationId: id }),
  setSelectedAgent: (id) => set({ selectedAgentId: id }),
  setSelectedTask: (id) => set({ selectedTaskId: id }),
  openCreateAgentModal: (workstationId) =>
    set({
      showCreateAgentModal: true,
      selectedWorkstationId: workstationId ?? get().selectedWorkstationId,
    }),
  closeCreateAgentModal: () => set({ showCreateAgentModal: false }),
  setWsConnected: (connected) => set({ wsConnected: connected }),
  setWsSend: (fn) => set({ wsSend: fn }),

  // Streaming actions
  setStreamingSubtask: (subtaskId) => set({ streamingSubtaskId: subtaskId, streamingContent: '' }),
  appendStreamingContent: (chunk) => set((state) => ({
    streamingContent: state.streamingContent + chunk,
  })),
  clearStreamingContent: () => set({ streamingSubtaskId: null, streamingContent: '' }),

  // Task Dashboard actions
  setShowTaskDashboard: (show) => set({ showTaskDashboard: show }),
  toggleTaskDashboard: () => set((state) => ({ showTaskDashboard: !state.showTaskDashboard })),
  setExpandedTask: (id) => set({ expandedTaskId: id }),
  setSelectedSubtask: (id) => set({ selectedSubtaskId: id }),
}));
