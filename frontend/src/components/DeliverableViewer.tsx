import React, { useState, useEffect, useMemo } from 'react';
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown';
import type { Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useStore } from '../store/useStore';
import type { ScratchpadEntry } from '../types';

/**
 * Custom URL transform: strip bogus prefixes LLMs sometimes prepend
 * (e.g. "sandbox:/api/...") BEFORE the default sanitiser runs,
 * so that relative /api/ URLs survive the protocol check.
 */
function urlTransform(url: string): string {
  const cleaned = url.replace(/^sandbox:/, '');
  return defaultUrlTransform(cleaned);
}

/** Custom ReactMarkdown components: open links in new tab, lazy images. */
const mdComponents: Components = {
  img: ({ node, ...rest }) => (
    <img loading="lazy" style={{ maxWidth: '100%', height: 'auto' }} {...rest} />
  ),
  a: ({ node, children, ...rest }) => (
    <a target="_blank" rel="noopener noreferrer" {...rest}>
      {children}
    </a>
  ),
};

export const DeliverableViewer: React.FC = () => {
  const { tasks, agents, scratchpadEntries, selectedTaskId, setSelectedTask } = useStore();
  const [activeTab, setActiveTab] = useState<'subtasks' | 'scratchpad'>('subtasks');

  const task = tasks.find((t) => t.id === selectedTaskId);

  // Merge scratchpad: task.scratchpad (persisted) + store entries (realtime)
  const taskScratchpad = useMemo(() => {
    if (!task) return [];
    const map = new Map<string, ScratchpadEntry>();
    // Persisted entries from task
    if (task.scratchpad) {
      for (const e of task.scratchpad) {
        map.set(e.key, { ...e, task_id: e.task_id || task.id });
      }
    }
    // Realtime entries from store (override persisted if same key)
    for (const e of scratchpadEntries) {
      if (e.task_id === task.id) {
        map.set(e.key, e);
      }
    }
    return Array.from(map.values());
  }, [task, scratchpadEntries]);

  // Close on ESC
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSelectedTask(null);
    };
    if (task) {
      window.addEventListener('keydown', handleKey);
      return () => window.removeEventListener('keydown', handleKey);
    }
  }, [task, setSelectedTask]);

  if (!task) return null;

  const getAgentName = (id: string) =>
    id === 'pm-agent' ? 'PM' : agents.find((a) => a.id === id)?.name || id.slice(0, 8);

  return (
    <div className="deliverable-overlay" onClick={() => setSelectedTask(null)}>
      <div className="deliverable-panel" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="deliverable-header">
          <h2>{task.title}</h2>
          <div className="deliverable-header-right">
            <span className={`status-badge status-${task.status}`}>{task.status}</span>
            {task.progress !== undefined && task.progress < 100 && (
              <span className="progress-badge">{task.progress}%</span>
            )}
            <button className="close-btn" onClick={() => setSelectedTask(null)}>
              X
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div className="deliverable-tabs">
          <button
            className={activeTab === 'subtasks' ? 'active' : ''}
            onClick={() => setActiveTab('subtasks')}
          >
            Subtasks ({task.subtasks.length})
          </button>
          <button
            className={activeTab === 'scratchpad' ? 'active' : ''}
            onClick={() => setActiveTab('scratchpad')}
          >
            Scratchpad ({taskScratchpad.length})
          </button>
        </div>

        {/* Scrollable content area — single scroll container */}
        <div className="deliverable-body">
          {activeTab === 'subtasks' &&
            (task.subtasks.length > 0 ? (
              task.subtasks.map((st) => (
                <div key={st.id} className="subtask-output-card">
                  <div className="subtask-card-header">
                    <span>
                      {st.status === 'done' ? '[OK]' : st.status === 'in_progress' ? '[..]' : '[  ]'}{' '}
                      {st.title}
                    </span>
                    {st.assigned_to && (
                      <span className="agent-tag">{getAgentName(st.assigned_to)}</span>
                    )}
                  </div>
                  {st.output ? (
                    <div className="subtask-output-content">
                      <ReactMarkdown remarkPlugins={[remarkGfm]} urlTransform={urlTransform} components={mdComponents}>{st.output}</ReactMarkdown>
                    </div>
                  ) : (
                    <div className="subtask-no-output">No output yet</div>
                  )}
                </div>
              ))
            ) : (
              <div className="empty-state">No subtasks yet</div>
            ))}

          {activeTab === 'scratchpad' &&
            (taskScratchpad.length > 0 ? (
              taskScratchpad.map((e, i) => (
                <div key={i} className="scratchpad-entry-card">
                  <div className="entry-header">
                    <strong>[{e.key}]</strong> by {e.author_name}
                  </div>
                  <div className="entry-content">{e.content}</div>
                </div>
              ))
            ) : (
              <div className="empty-state">No scratchpad entries yet</div>
            ))}

          {/* Final Output — inside scroll container */}
          {task.output && (
            <div className="final-output-section">
              <h3>Final Deliverable</h3>
              <div className="final-output-body">
                <ReactMarkdown remarkPlugins={[remarkGfm]} urlTransform={urlTransform} components={mdComponents}>{task.output}</ReactMarkdown>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
