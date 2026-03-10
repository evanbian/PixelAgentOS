import { useEffect, useRef, useCallback } from 'react';
import { useStore } from '../store/useStore';
import type { WSMessage, Agent, Task, SubTask, InteractionLog, ScratchpadEntry, TaskMetrics } from '../types';

const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/ws';
const RECONNECT_DELAY = 3000;

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const {
    setWsConnected,
    setWsSend,
    setAgents,
    setTasks,
    addAgent,
    removeAgent,
    updateAgentStatus,
    addTask,
    removeTask,
    updateTask,
    addSubtask,
    updateSubtask,
    addLog,
    addLogs,
    addActivity,
    addScratchpadEntry,
    clearScratchpadForTask,
    setTaskMetrics,
  } = useStore();

  const handleMessage = useCallback(
    (msg: WSMessage) => {
      const { event, data } = msg;

      switch (event) {
        case 'init': {
          const agents = (data.agents as Agent[]) || [];
          const tasks = (data.tasks as Task[]) || [];
          setAgents(agents);
          setTasks(tasks);

          // Restore scratchpad entries from tasks
          for (const task of tasks) {
            if (task.scratchpad && task.scratchpad.length > 0) {
              for (const entry of task.scratchpad) {
                addScratchpadEntry({
                  ...entry,
                  task_id: entry.task_id || task.id,
                });
              }
            }
          }

          // Rebuild chat history from agent short-term memory
          const historyLogs: Array<Omit<InteractionLog, 'id'> & { timestamp?: Date }> = [];
          for (const agent of agents) {
            if (agent.memory?.short_term) {
              for (const item of agent.memory.short_term) {
                historyLogs.push({
                  from_id: item.role === 'user' ? 'human' : agent.id,
                  to_id: item.role === 'user' ? agent.id : 'human',
                  content: item.content,
                  type: 'chat',
                  timestamp: new Date(item.timestamp),
                });
              }
            }
          }
          if (historyLogs.length > 0) {
            addLogs(historyLogs);
          }
          break;
        }
        case 'agent:created': {
          addAgent(data as unknown as Agent);
          addActivity({
            type: 'system',
            content: `${(data as Agent).name} joined as ${(data as Agent).role}`,
            timestamp: new Date(),
          });
          break;
        }
        case 'agent:removed': {
          removeAgent(data.agent_id as string);
          break;
        }
        case 'agent:status': {
          updateAgentStatus(
            data.agent_id as string,
            data.status as Agent['status']
          );
          if (data.status !== 'idle') {
            const agentName = useStore.getState().agents.find(
              a => a.id === data.agent_id
            )?.name || (data.agent_id as string).slice(0, 8);
            addActivity({
              type: 'status',
              content: `${agentName} is ${data.status as string}`,
              agent_name: agentName,
              timestamp: new Date(),
            });
          }
          break;
        }
        case 'agent:message': {
          const fromId = data.from_id as string;
          const toId = data.to_id as string;
          const msgType = data.type as string;
          const content = data.content as string;

          // Detect agent-to-agent conversation
          const storeAgents = useStore.getState().agents;
          const fromAgent = storeAgents.find(a => a.id === fromId);
          const toAgent = storeAgents.find(a => a.id === toId);
          const isAgentToAgent = fromAgent && toAgent && fromId !== 'pm-agent' && toId !== 'human' && toId !== 'all';

          if (isAgentToAgent) {
            addActivity({
              type: 'agent',
              content: `💬 ${fromAgent.name} → ${toAgent.name}: ${content}`,
              agent_name: fromAgent.name,
              timestamp: new Date(),
            });
          } else if (fromId === 'pm-agent' || msgType === 'agent') {
            const agentName = fromId === 'pm-agent'
              ? 'PM'
              : fromAgent?.name || fromId.slice(0, 8);
            addActivity({
              type: fromId === 'pm-agent' ? 'pm' : 'agent',
              content,
              agent_name: agentName,
              timestamp: new Date(),
            });
          } else {
            addLog({
              from_id: fromId,
              to_id: toId,
              content,
              type: 'chat',
            });
          }
          break;
        }
        case 'task:created': {
          addTask(data as unknown as Task);
          addActivity({
            type: 'system',
            content: `New task: "${(data as Task).title}"`,
            timestamp: new Date(),
          });
          // Auto-show task dashboard and expand the new task
          useStore.getState().setShowTaskDashboard(true);
          useStore.getState().setExpandedTask((data as Task).id);
          break;
        }
        case 'task:removed': {
          removeTask(data.task_id as string);
          break;
        }
        case 'task:update': {
          const taskUpdate: Partial<Task> = {
            status: data.status as Task['status'],
            progress: data.progress as number | undefined,
            output: data.output as string | undefined,
          };
          if (data.schedule !== undefined) {
            taskUpdate.schedule = data.schedule as string | null;
          }
          if (data.next_run_at !== undefined) {
            taskUpdate.next_run_at = data.next_run_at as string | null;
          }
          if (data.last_run_at !== undefined) {
            taskUpdate.last_run_at = data.last_run_at as string | null;
          }
          updateTask(data.task_id as string, taskUpdate);
          addActivity({
            type: 'system',
            content: `Task: ${data.status as string} (${(data.progress as number) ?? 0}%)`,
            timestamp: new Date(),
          });
          // Auto-show + expand when task becomes active
          if (data.status === 'in_progress') {
            useStore.getState().setShowTaskDashboard(true);
            useStore.getState().setExpandedTask(data.task_id as string);
          }
          if (data.status === 'done' && data.output) {
            addLog({
              from_id: 'system',
              to_id: 'all',
              content: `__DELIVERABLE__${data.task_id as string}`,
              type: 'deliverable',
            });
          }
          if (data.status === 'cancelled') {
            // Clear streaming state if the cancelled task was streaming
            const store = useStore.getState();
            if (store.streamingSubtaskId) {
              store.clearStreamingContent();
            }
          }
          break;
        }
        case 'task:subtask': {
          const subtask = data.subtask as SubTask;
          if (subtask.title) {
            addSubtask(data.parent_id as string, subtask);
            addActivity({
              type: 'subtask',
              content: `Subtask: ${subtask.title}`,
              timestamp: new Date(),
            });
          } else if (subtask.id) {
            updateSubtask(data.parent_id as string, subtask.id, subtask);
            if (subtask.status === 'done') {
              addActivity({
                type: 'subtask',
                content: `Subtask completed: ${subtask.id.slice(0, 8)}...`,
                timestamp: new Date(),
              });
            }
          }
          break;
        }
        case 'task:assigned': {
          updateTask(data.task_id as string, {
            assigned_to: data.agent_ids as string[],
          });
          break;
        }
        case 'system:log': {
          addActivity({
            type: 'system',
            content: data.message as string,
            timestamp: new Date(),
          });
          break;
        }
        case 'subtask:stream': {
          const subtaskId = data.subtask_id as string;
          const taskId = data.task_id as string;
          const chunk = data.chunk as string;
          const store = useStore.getState();
          if (store.streamingSubtaskId !== subtaskId) {
            store.setStreamingSubtask(subtaskId);
            // Auto-show task dashboard and expand parent task
            store.setShowTaskDashboard(true);
            store.setExpandedTask(taskId);
            // Find subtask title for activity
            let stTitle = subtaskId.slice(0, 8);
            for (const t of store.tasks) {
              const found = t.subtasks.find((s) => s.id === subtaskId);
              if (found) { stTitle = found.title; break; }
            }
            addActivity({
              type: 'subtask',
              content: `🔄 Executing: ${stTitle}`,
              agent_name: undefined,
              timestamp: new Date(),
            });
          }
          store.appendStreamingContent(chunk);
          break;
        }
        case 'subtask:stream_end': {
          const stId = data.subtask_id as string;
          const stStore = useStore.getState();
          if (stStore.streamingSubtaskId === stId) {
            // Find subtask title for activity
            let endTitle = stId.slice(0, 8);
            for (const t of stStore.tasks) {
              const found = t.subtasks.find((s) => s.id === stId);
              if (found) { endTitle = found.title; break; }
            }
            addActivity({
              type: 'subtask',
              content: `✅ Completed: ${endTitle}`,
              timestamp: new Date(),
            });
            stStore.clearStreamingContent();
          }
          break;
        }
        case 'task:metrics': {
          const taskId = data.task_id as string;
          setTaskMetrics(taskId, data as unknown as TaskMetrics);
          const dur = data.total_duration_s as number;
          const tools = data.tool_call_count as number;
          addActivity({
            type: 'system',
            content: `Task metrics: ${dur}s, ${tools} tool calls, ${data.reflection_count as number} reflections`,
            timestamp: new Date(),
          });
          break;
        }
        case 'scratchpad:update': {
          addScratchpadEntry(data as unknown as ScratchpadEntry);
          break;
        }
        case 'scratchpad:clear': {
          clearScratchpadForTask(data.task_id as string);
          break;
        }
        default:
          break;
      }
    },
    [
      setAgents, setTasks, addAgent, removeAgent,
      updateAgentStatus, addTask, removeTask,
      updateTask, addSubtask, updateSubtask, addLog, addLogs,
      addActivity, addScratchpadEntry, clearScratchpadForTask, setTaskMetrics,
    ]
  );

  const send = useCallback((event: string, data: Record<string, unknown>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ event, data }));
    }
  }, []);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      setWsConnected(true);
      setWsSend(send);
      console.log('[WS] Connected');
    };

    ws.onmessage = (event) => {
      try {
        const msg: WSMessage = JSON.parse(event.data);
        handleMessage(msg);
      } catch (e) {
        console.error('[WS] Parse error:', e);
      }
    };

    ws.onerror = (error) => {
      console.error('[WS] Error:', error);
    };

    ws.onclose = () => {
      setWsConnected(false);
      setWsSend(null);
      console.log('[WS] Disconnected. Reconnecting...');
      reconnectTimer.current = setTimeout(connect, RECONNECT_DELAY);
    };
  }, [handleMessage, setWsConnected, setWsSend, send]);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { send };
}
