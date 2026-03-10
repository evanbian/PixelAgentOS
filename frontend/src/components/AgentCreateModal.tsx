import React, { useState, useEffect, useMemo } from 'react';
import { useStore } from '../store/useStore';
import type { AgentRole, LLMProvider, RoleOption, SkillOption } from '../types';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const AVATAR_COLORS = [
  '#4fc3f7', '#81c784', '#ffb74d', '#f48fb1',
  '#ce93d8', '#80deea', '#a5d6a7', '#fff176',
];

interface Props {
  onAgentCreated: (agent: unknown) => void;
}

export const AgentCreateModal: React.FC<Props> = ({ onAgentCreated }) => {
  const { showCreateAgentModal, closeCreateAgentModal, selectedWorkstationId } = useStore();
  const [providers, setProviders] = useState<LLMProvider[]>([]);
  const [roleOptions, setRoleOptions] = useState<RoleOption[]>([]);
  const [skillOptions, setSkillOptions] = useState<SkillOption[]>([]);  // for display names
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const [form, setForm] = useState({
    name: '',
    role: 'Developer' as AgentRole,
    avatar_index: 0,
    skills: ['code'] as string[],
    system_prompt: '',
    provider: 'deepseek',
    model: 'deepseek/deepseek-chat',
    api_key: '',
    custom_api_base: '',
  });

  useEffect(() => {
    // Fetch LLM providers
    fetch(`${API_URL}/api/models`)
      .then((r) => r.json())
      .then((d) => {
        const list: LLMProvider[] = d.providers || [];
        setProviders(list);
        if (list.length > 0) {
          const p = list[0];
          const m = p.models[0];
          setForm((prev) => ({
            ...prev,
            provider: p.id,
            model: m?.id || '',
          }));
        }
      })
      .catch(() => {});

    // Fetch roles from API
    fetch(`${API_URL}/api/agents/roles`)
      .then((r) => r.json())
      .then((data: RoleOption[]) => {
        setRoleOptions(data);
        // Pre-fill for default role
        const defaultRole = data.find((r) => r.id === 'Developer');
        if (defaultRole) {
          setForm((prev) => ({
            ...prev,
            skills: defaultRole.default_skills,
            system_prompt: prev.system_prompt || defaultRole.system_prompt,
          }));
        }
      })
      .catch(() => {});

    // Fetch skills from API
    fetch(`${API_URL}/api/agents/skills`)
      .then((r) => r.json())
      .then((data: SkillOption[]) => {
        setSkillOptions(data);
      })
      .catch(() => {});
  }, []);

  const selectedProvider = useMemo(
    () => providers.find((p) => p.id === form.provider),
    [providers, form.provider],
  );

  // Build a skill id → display info map for showing default skills
  const skillDisplayMap = useMemo(() => {
    const m: Record<string, SkillOption> = {};
    for (const s of skillOptions) m[s.id] = s;
    return m;
  }, [skillOptions]);

  // Tool ID → friendly name mapping
  const TOOL_LABELS: Record<string, string> = {
    code_execute: '⚙️ Code Execute',
    write_document: '📝 Write Docs',
    web_search: '🌐 Web Search',
    summarize_text: '📋 Summarize',
    analyze_data: '📈 Data Analysis',
    create_plan: '📅 Planning',
    http_request: '🔗 HTTP Request',
  };

  // Current role's capabilities for display
  const selectedRole = useMemo(
    () => roleOptions.find((r) => r.id === form.role),
    [roleOptions, form.role],
  );

  const handleProviderChange = (providerId: string) => {
    const provider = providers.find((p) => p.id === providerId);
    const firstModel = provider?.models[0];
    setForm((prev) => ({
      ...prev,
      provider: providerId,
      model: firstModel?.id || '',
      custom_api_base: '',
    }));
  };

  const handleRoleChange = (role: AgentRole) => {
    const roleConfig = roleOptions.find((r) => r.id === role);
    setForm((prev) => ({
      ...prev,
      role,
      skills: roleConfig?.default_skills || [],
      system_prompt: roleConfig?.system_prompt || '',
    }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.name.trim()) { setError('请输入 Agent 名称'); return; }
    if (!selectedWorkstationId) { setError('未选择工位'); return; }
    if (!form.api_key.trim()) { setError('请输入 API Key'); return; }

    setLoading(true);
    setError('');

    let modelId = form.model;
    const apiBase = form.custom_api_base || selectedProvider?.api_base || '';

    const nativeProviders = ['deepseek', 'anthropic', 'openai'];
    const needsApiBase = !nativeProviders.includes(form.provider);

    try {
      const body: Record<string, unknown> = {
        name: form.name,
        role: form.role,
        avatar_index: form.avatar_index,
        skills: form.skills,
        system_prompt: form.system_prompt,
        workstation_id: selectedWorkstationId,
        model: modelId,
        api_key: form.api_key,
      };

      if (needsApiBase && apiBase) {
        body.api_key = `${form.api_key}|||${apiBase}`;
      }

      const res = await fetch(`${API_URL}/api/agents`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      if (!res.ok) throw new Error(await res.text());
      const agent = await res.json();
      onAgentCreated(agent);
      closeCreateAgentModal();
      setForm({
        name: '', role: 'Developer', avatar_index: 0,
        skills: roleOptions.find((r) => r.id === 'Developer')?.default_skills || ['code'],
        system_prompt: '', provider: providers[0]?.id || 'deepseek',
        model: providers[0]?.models[0]?.id || 'deepseek/deepseek-chat',
        api_key: '', custom_api_base: '',
      });
    } catch (err: unknown) {
      setError((err as Error).message || '创建 Agent 失败');
    } finally {
      setLoading(false);
    }
  };

  if (!showCreateAgentModal) return null;

  return (
    <div className="modal-overlay" onClick={closeCreateAgentModal}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <span>🧑‍💼 Hire New Agent</span>
          <button className="close-btn" onClick={closeCreateAgentModal}>✕</button>
        </div>

        <form onSubmit={handleSubmit}>
          {/* Name */}
          <div className="form-group">
            <label>Name</label>
            <input
              className="pixel-input"
              placeholder="e.g. Alice, CodeBot..."
              value={form.name}
              onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))}
              maxLength={20}
            />
          </div>

          {/* Role */}
          <div className="form-group">
            <label>Role</label>
            <div className="role-grid">
              {roleOptions.map((r) => (
                <button
                  key={r.id}
                  type="button"
                  className={`role-btn ${form.role === r.id ? 'active' : ''}`}
                  onClick={() => handleRoleChange(r.id)}
                  title={r.description}
                >
                  <span>{r.emoji}</span>
                  <span>{r.display_name}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Avatar */}
          <div className="form-group">
            <label>Avatar Color</label>
            <div className="avatar-grid">
              {AVATAR_COLORS.map((color, i) => (
                <button
                  key={i}
                  type="button"
                  className={`avatar-btn ${form.avatar_index === i ? 'active' : ''}`}
                  style={{ background: color }}
                  onClick={() => setForm((p) => ({ ...p, avatar_index: i }))}
                />
              ))}
            </div>
          </div>

          {/* Capabilities (read-only) */}
          {selectedRole && (
            <div className="form-group">
              <label>Capabilities</label>
              <div className="capabilities-display">
                <div className="cap-section">
                  <span className="cap-label">Core Tools</span>
                  <div className="cap-tags">
                    {selectedRole.core_tool_ids.map((tid) => (
                      <span key={tid} className="cap-tag core">
                        {TOOL_LABELS[tid] || tid}
                      </span>
                    ))}
                  </div>
                </div>
                {selectedRole.default_skills.length > 0 && (
                  <div className="cap-section">
                    <span className="cap-label">Skills</span>
                    <div className="cap-tags">
                      {selectedRole.default_skills.map((sid) => {
                        const info = skillDisplayMap[sid];
                        return (
                          <span key={sid} className="cap-tag skill" title={info?.description}>
                            {info ? `${info.emoji || '🔧'} ${info.display_name}` : sid}
                          </span>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* LLM Provider */}
          <div className="form-group">
            <label>LLM Provider</label>
            <select
              className="pixel-input"
              value={form.provider}
              onChange={(e) => handleProviderChange(e.target.value)}
            >
              {providers.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
              {providers.length === 0 && (
                <option value="deepseek">DeepSeek</option>
              )}
            </select>
          </div>

          {/* Model */}
          <div className="form-group">
            <label>Model</label>
            <select
              className="pixel-input"
              value={form.model}
              onChange={(e) => setForm((p) => ({ ...p, model: e.target.value }))}
            >
              {selectedProvider?.models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}{m.recommended ? ' ⭐' : ''}
                </option>
              ))}
            </select>
          </div>

          {/* API Key */}
          <div className="form-group">
            <label>API Key</label>
            <input
              className="pixel-input"
              type="password"
              placeholder={`输入 ${selectedProvider?.name || ''} API Key`}
              value={form.api_key}
              onChange={(e) => setForm((p) => ({ ...p, api_key: e.target.value }))}
              autoComplete="off"
            />
            {selectedProvider && (
              <div className="form-hint">
                API Base: {form.custom_api_base || selectedProvider.api_base}
              </div>
            )}
          </div>

          {/* Custom API Base (optional) */}
          <div className="form-group">
            <label>Custom API Base (optional)</label>
            <input
              className="pixel-input"
              placeholder={selectedProvider?.api_base || 'https://...'}
              value={form.custom_api_base}
              onChange={(e) => setForm((p) => ({ ...p, custom_api_base: e.target.value }))}
            />
          </div>

          {/* System Prompt */}
          <div className="form-group">
            <label>System Prompt</label>
            <textarea
              className="pixel-input"
              placeholder="Custom instructions for this agent..."
              value={form.system_prompt}
              onChange={(e) => setForm((p) => ({ ...p, system_prompt: e.target.value }))}
              rows={4}
            />
          </div>

          {selectedWorkstationId && (
            <div className="workstation-badge">
              📍 Workstation: {selectedWorkstationId}
            </div>
          )}

          {error && <div className="error-msg">⚠️ {error}</div>}

          <div className="modal-actions">
            <button type="button" className="btn-secondary" onClick={closeCreateAgentModal}>
              Cancel
            </button>
            <button type="submit" className="btn-primary" disabled={loading}>
              {loading ? '⏳ Hiring...' : '✅ Hire Agent'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
