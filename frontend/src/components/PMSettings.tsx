import React, { useState, useEffect, useMemo } from 'react';
import type { LLMProvider } from '../types';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export const PMSettings: React.FC = () => {
  const [open, setOpen] = useState(false);
  const [configured, setConfigured] = useState(false);
  const [currentModel, setCurrentModel] = useState('');
  const [currentKeyMasked, setCurrentKeyMasked] = useState('');

  // Form state
  const [providers, setProviders] = useState<LLMProvider[]>([]);
  const [provider, setProvider] = useState('');
  const [model, setModel] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [customBase, setCustomBase] = useState('');
  const [saving, setSaving] = useState(false);

  // Check PM config status on mount
  useEffect(() => {
    fetch(`${API_URL}/api/config/pm/status`)
      .then((r) => r.json())
      .then((d) => {
        setConfigured(d.configured);
        setCurrentModel(d.model || '');
      })
      .catch(() => {});

    fetch(`${API_URL}/api/config/pm`)
      .then((r) => r.json())
      .then((d) => {
        setCurrentKeyMasked(d.api_key || '');
      })
      .catch(() => {});

    fetch(`${API_URL}/api/models`)
      .then((r) => r.json())
      .then((d) => {
        const list: LLMProvider[] = d.providers || [];
        setProviders(list);
        if (list.length > 0) {
          setProvider(list[0].id);
          setModel(list[0].models[0]?.id || '');
        }
      })
      .catch(() => {});
  }, []);

  const selectedProvider = useMemo(
    () => providers.find((p) => p.id === provider),
    [providers, provider],
  );

  const handleProviderChange = (providerId: string) => {
    const p = providers.find((pr) => pr.id === providerId);
    setProvider(providerId);
    setModel(p?.models[0]?.id || '');
    setCustomBase('');
  };

  const handleSave = async () => {
    if (!model.trim() || !apiKey.trim()) return;
    setSaving(true);
    try {
      const nativeProviders = ['deepseek', 'anthropic', 'openai'];
      const needsApiBase = !nativeProviders.includes(provider);
      const apiBase = customBase || selectedProvider?.api_base || '';
      let finalKey = apiKey;
      if (needsApiBase && apiBase) {
        finalKey = `${apiKey}|||${apiBase}`;
      }

      const resp = await fetch(`${API_URL}/api/config/pm`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: model.trim(), api_key: finalKey }),
      });

      if (resp.ok) {
        setConfigured(true);
        setCurrentModel(model.trim());
        setCurrentKeyMasked('****' + apiKey.slice(-4));
        setApiKey('');
        setOpen(false);
      }
    } finally {
      setSaving(false);
    }
  };

  const handleClear = async () => {
    await fetch(`${API_URL}/api/config/pm`, { method: 'DELETE' });
    setConfigured(false);
    setCurrentModel('');
    setCurrentKeyMasked('');
  };

  return (
    <div className="pm-settings-inline">
      <button
        className={`pm-settings-btn ${configured ? 'configured' : 'not-configured'}`}
        onClick={() => setOpen(!open)}
        title={configured ? `PM: ${currentModel}` : 'PM not configured'}
      >
        {configured ? '🤖 PM' : '⚠️ PM'}
      </button>

      {open && (
        <div className="pm-settings-dropdown">
          <div className="pm-settings-header">
            PM Configuration
            <span className={`pm-status ${configured ? 'ok' : 'warn'}`}>
              {configured ? '✅' : '❌'}
            </span>
          </div>

          {configured && (
            <div className="pm-current">
              <div className="pm-current-row">
                <span className="pm-current-label">Model:</span>
                <span className="pm-current-value">{currentModel}</span>
              </div>
              <div className="pm-current-row">
                <span className="pm-current-label">Key:</span>
                <span className="pm-current-value">{currentKeyMasked}</span>
              </div>
              <button className="btn-danger-sm" onClick={handleClear}>Clear</button>
            </div>
          )}

          <div className="pm-config-form">
            <div className="form-group">
              <label>Provider</label>
              <select
                className="pixel-input"
                value={provider}
                onChange={(e) => handleProviderChange(e.target.value)}
              >
                {providers.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </div>
            <div className="form-group">
              <label>Model</label>
              <select
                className="pixel-input"
                value={model}
                onChange={(e) => setModel(e.target.value)}
              >
                {selectedProvider?.models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}{m.recommended ? ' *' : ''}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-group">
              <label>API Key</label>
              <input
                className="pixel-input"
                type="password"
                placeholder={`${selectedProvider?.name || ''} API Key`}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                autoComplete="off"
              />
            </div>
            <div className="form-group">
              <label>Custom API Base (optional)</label>
              <input
                className="pixel-input"
                placeholder={selectedProvider?.api_base || 'https://...'}
                value={customBase}
                onChange={(e) => setCustomBase(e.target.value)}
              />
            </div>
            <button
              className="btn-primary"
              onClick={handleSave}
              disabled={saving || !model.trim() || !apiKey.trim()}
            >
              {saving ? '...' : 'Save PM Config'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
