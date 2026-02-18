import React, { useState, useEffect, useCallback } from 'react';
import { API_BASE } from '../config';

type AuthUser = {
  username: string;
  email: string;
  role: string;
};

type UserManagementProps = {
  user?: AuthUser | null;
};

// ---------------------------------------------------------------------------
// Branding Settings Sub-Component
// ---------------------------------------------------------------------------
const BrandingSettings: React.FC = () => {
  const [brandData, setBrandData] = useState({
    company_name: '',
    company_subtitle: '',
    login_hero_title: '',
    login_hero_description: '',
    login_hero_features: [] as string[],
    company_logo_url: '',
    primary_color: '#667eea',
    secondary_color: '#764ba2',
  });
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState('');
  const [logoUploading, setLogoUploading] = useState(false);
  const [newFeature, setNewFeature] = useState('');

  const fetchBranding = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/settings/branding`);
      if (res.ok) {
        const data = await res.json();
        setBrandData(prev => ({ ...prev, ...data }));
      }
    } catch {}
  }, []);

  useEffect(() => { fetchBranding(); }, [fetchBranding]);

  const authToken = localStorage.getItem('auth_token') || '';
  const authHeader = authToken ? `Bearer ${authToken}` : '';

  const handleSave = async () => {
    if (!authHeader) { setMsg('⚠️ Please log in first'); return; }
    setSaving(true); setMsg('');
    try {
      const res = await fetch(`${API_BASE}/admin/settings/branding`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: authHeader },
        body: JSON.stringify({
          ...brandData,
          login_hero_features: brandData.login_hero_features,
        }),
      });
      if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || `HTTP ${res.status}`); }
      setMsg('✅ Branding saved successfully');
      setTimeout(() => setMsg(''), 4000);
    } catch (e: any) { setMsg(`⚠️ ${e.message}`); }
    finally { setSaving(false); }
  };

  const handleLogoUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!authHeader) { setMsg('⚠️ Please log in first'); return; }
    if (file.size > 2 * 1024 * 1024) { setMsg('⚠️ Logo must be under 2 MB'); return; }
    setLogoUploading(true); setMsg('');
    try {
      const res = await fetch(`${API_BASE}/admin/settings/branding/logo`, {
        method: 'POST',
        headers: { 'Content-Type': file.type, Authorization: authHeader },
        body: file,
      });
      if (!res.ok) { const err = await res.json().catch(() => ({})); throw new Error(err.detail || 'Upload failed'); }
      const data = await res.json();
      setBrandData(prev => ({ ...prev, company_logo_url: data.logo_url }));
      setMsg('✅ Logo uploaded');
      setTimeout(() => setMsg(''), 4000);
    } catch (err: any) { setMsg(`⚠️ ${err.message}`); }
    finally { setLogoUploading(false); }
  };

  const removeLogo = () => setBrandData(prev => ({ ...prev, company_logo_url: '' }));

  const addFeature = () => {
    if (newFeature.trim()) {
      setBrandData(prev => ({ ...prev, login_hero_features: [...prev.login_hero_features, newFeature.trim()] }));
      setNewFeature('');
    }
  };
  const removeFeature = (idx: number) =>
    setBrandData(prev => ({ ...prev, login_hero_features: prev.login_hero_features.filter((_, i) => i !== idx) }));

  const inputStyle: React.CSSProperties = {
    width: '100%', padding: '8px 12px', borderRadius: '6px',
    border: '1px solid var(--color-border, #ddd)', boxSizing: 'border-box',
    background: 'var(--color-surface, #fff)', color: 'var(--color-text-primary, #333)',
    fontSize: '14px',
  };
  const labelStyle: React.CSSProperties = { fontWeight: 600, fontSize: '13px', marginBottom: '4px', display: 'block', color: 'var(--color-text-primary, #333)' };
  const logoPreviewUrl = brandData.company_logo_url
    ? (brandData.company_logo_url.startsWith('http') ? brandData.company_logo_url : `${API_BASE}${brandData.company_logo_url}`)
    : '';

  return (
    <div style={{ maxWidth: '700px' }}>
      <h3 style={{ marginTop: 0, marginBottom: '16px' }}>🎨 Branding & Login Page Settings</h3>
      <p style={{ fontSize: '13px', color: 'var(--color-text-secondary, #888)', marginBottom: '20px' }}>
        Customize the company name, logo, and hero content shown on the login page.
        Changes take effect immediately for new visitors.
      </p>

      {msg && <div style={{ padding: '10px', borderRadius: '6px', marginBottom: '16px', background: msg.startsWith('✅') ? '#dcfce7' : '#fee2e2', color: msg.startsWith('✅') ? '#166534' : '#991b1b' }}>{msg}</div>}

      <div style={{ display: 'grid', gap: '16px', gridTemplateColumns: '1fr 1fr' }}>
        <div>
          <label style={labelStyle}>Company Name</label>
          <input value={brandData.company_name} onChange={e => setBrandData({...brandData, company_name: e.target.value})} style={inputStyle} />
        </div>
        <div>
          <label style={labelStyle}>Subtitle</label>
          <input value={brandData.company_subtitle} onChange={e => setBrandData({...brandData, company_subtitle: e.target.value})} style={inputStyle} />
        </div>
        <div>
          <label style={labelStyle}>Primary Color</label>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            <input type="color" value={brandData.primary_color} onChange={e => setBrandData({...brandData, primary_color: e.target.value})} style={{ width: '40px', height: '36px', border: 'none', cursor: 'pointer' }} />
            <input value={brandData.primary_color} onChange={e => setBrandData({...brandData, primary_color: e.target.value})} style={{...inputStyle, flex: 1}} />
          </div>
        </div>
        <div>
          <label style={labelStyle}>Secondary Color</label>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            <input type="color" value={brandData.secondary_color} onChange={e => setBrandData({...brandData, secondary_color: e.target.value})} style={{ width: '40px', height: '36px', border: 'none', cursor: 'pointer' }} />
            <input value={brandData.secondary_color} onChange={e => setBrandData({...brandData, secondary_color: e.target.value})} style={{...inputStyle, flex: 1}} />
          </div>
        </div>
      </div>

      {/* Logo */}
      <div style={{ marginTop: '20px' }}>
        <label style={labelStyle}>Company Logo</label>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {logoPreviewUrl ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <img src={logoPreviewUrl} alt="Logo preview" style={{ maxHeight: '48px', maxWidth: '160px', objectFit: 'contain', border: '1px solid var(--color-border)', borderRadius: '4px', padding: '4px' }} />
              <button onClick={removeLogo} style={{ padding: '4px 8px', background: '#ef4444', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer', fontSize: '11px' }}>Remove</button>
            </div>
          ) : (
            <span style={{ fontSize: '13px', color: '#888' }}>No logo uploaded</span>
          )}
          <label style={{ padding: '6px 14px', background: '#2563eb', color: 'white', borderRadius: '4px', cursor: logoUploading ? 'wait' : 'pointer', fontSize: '13px', fontWeight: 600 }}>
            {logoUploading ? 'Uploading...' : 'Upload Logo'}
            <input type="file" accept="image/png,image/jpeg,image/gif,image/svg+xml,image/webp" onChange={handleLogoUpload} style={{ display: 'none' }} />
          </label>
        </div>
        <p style={{ fontSize: '11px', color: '#999', marginTop: '4px' }}>PNG, JPEG, GIF, SVG, or WebP. Max 2 MB.</p>
      </div>

      {/* Hero section */}
      <div style={{ marginTop: '20px' }}>
        <label style={labelStyle}>Login Hero Title</label>
        <input value={brandData.login_hero_title} onChange={e => setBrandData({...brandData, login_hero_title: e.target.value})} style={inputStyle} />
      </div>
      <div style={{ marginTop: '12px' }}>
        <label style={labelStyle}>Login Hero Description</label>
        <textarea value={brandData.login_hero_description} onChange={e => setBrandData({...brandData, login_hero_description: e.target.value})} rows={3} style={{...inputStyle, resize: 'vertical'}} />
      </div>

      {/* Feature list */}
      <div style={{ marginTop: '16px' }}>
        <label style={labelStyle}>Feature Highlights (shown on login page)</label>
        {brandData.login_hero_features.map((f, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
            <span style={{ flex: 1, fontSize: '13px', padding: '6px 10px', background: 'var(--color-surface, #f9f9f9)', borderRadius: '4px', border: '1px solid var(--color-border, #ddd)', color: 'var(--color-text-primary, #333)' }}>✓ {f}</span>
            <button onClick={() => removeFeature(i)} style={{ padding: '2px 8px', background: '#ef4444', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer', fontSize: '11px' }}>✕</button>
          </div>
        ))}
        <div style={{ display: 'flex', gap: '8px', marginTop: '6px' }}>
          <input value={newFeature} onChange={e => setNewFeature(e.target.value)} onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), addFeature())} placeholder="Add a feature highlight..." style={{...inputStyle, flex: 1}} />
          <button onClick={addFeature} style={{ padding: '6px 14px', background: '#16a34a', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer', fontSize: '13px', fontWeight: 600 }}>Add</button>
        </div>
      </div>

      {/* Color preview */}
      <div style={{ marginTop: '20px', padding: '16px', borderRadius: '8px', background: `linear-gradient(135deg, ${brandData.primary_color} 0%, ${brandData.secondary_color} 100%)`, color: 'white' }}>
        <div style={{ fontSize: '13px', fontWeight: 600, marginBottom: '4px' }}>Preview: Login Page Gradient</div>
        <div style={{ fontSize: '11px', opacity: 0.8 }}>{brandData.primary_color} → {brandData.secondary_color}</div>
      </div>

      {/* Save */}
      <div style={{ marginTop: '20px', display: 'flex', gap: '10px' }}>
        <button onClick={handleSave} disabled={saving} style={{
          padding: '10px 24px', background: '#2563eb', color: 'white', border: 'none',
          borderRadius: '6px', cursor: saving ? 'wait' : 'pointer', fontWeight: 600, fontSize: '14px',
        }}>
          {saving ? 'Saving...' : '💾 Save Branding'}
        </button>
        <button onClick={fetchBranding} style={{
          padding: '10px 24px', background: '#6b7280', color: 'white', border: 'none',
          borderRadius: '6px', cursor: 'pointer', fontWeight: 600, fontSize: '14px',
        }}>
          ↩ Reset
        </button>
      </div>
    </div>
  );
};


// MFA user entry from admin endpoint
interface MFAUserEntry {
  username: string;
  mfa_enabled: boolean;
  created_at: string | null;
}

const UserManagement: React.FC<UserManagementProps> = ({ user }) => {
  const [users, setUsers] = useState([]);
  const [roles, setRoles] = useState([]);
  const [permissions, setPermissions] = useState([]);
  const [auditLogs, setAuditLogs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState('audit');
  const [showModal, setShowModal] = useState(false);
  const [modalType, setModalType] = useState('user');
  const [editingItem, setEditingItem] = useState(null);
  const [formData, setFormData] = useState({});
  const [error, setError] = useState('');
  // MFA tab state
  const [mfaUsers, setMfaUsers] = useState<MFAUserEntry[]>([]);
  const [mfaLoading, setMfaLoading] = useState(false);
  const [mfaMsg, setMfaMsg] = useState('');

  // --- Department + Navigation state ---
  const [departments, setDepartments] = useState<any[]>([]);
  const [navGroups, setNavGroups] = useState<any[]>([]);
  const [navItems, setNavItems] = useState<any[]>([]);
  const [visibilityMatrix, setVisibilityMatrix] = useState<any>(null);
  const [deptForm, setDeptForm] = useState({ name: '', description: '', sort_order: 0 });
  const [deptEditing, setDeptEditing] = useState<number | null>(null);
  const [deptMsg, setDeptMsg] = useState('');
  const [visMsg, setVisMsg] = useState('');
  // Track visibility changes: { [deptId]: { groups: Set<groupId>, items: Set<itemId> } }
  const [visEdits, setVisEdits] = useState<Record<number, { groups: Set<number>; items: Set<number> }>>({});

  // Navigation CRUD state
  const [navMsg, setNavMsg] = useState('');
  const [groupForm, setGroupForm] = useState({ key: '', label: '', icon: '', description: '', sort_order: 0, is_default: false });
  const [showEmojiPicker, setShowEmojiPicker] = useState(false);
  const [editingGroupId, setEditingGroupId] = useState<number | null>(null);

  // Permission matrix search & sort state
  const [permSearchQuery, setPermSearchQuery] = useState('');
  const [permSortBy, setPermSortBy] = useState<'resource' | 'action' | 'roles'>('resource');
  const [permSortDir, setPermSortDir] = useState<'asc' | 'desc'>('asc');

  const [itemForm, setItemForm] = useState({ key: '', label: '', icon: '', route: '', resource_key: '', nav_group_id: 0, sort_order: 0, is_active: true, is_action: false });
  const [editingItemId, setEditingItemId] = useState<number | null>(null);
  const [showAddItem, setShowAddItem] = useState<number | null>(null); // group id to show add-item form for
  
  // Audit log filters
  const [auditFilters, setAuditFilters] = useState({
    username: '',
    action: '',
    startDate: '',
    endDate: ''
  });

  useEffect(() => {
    loadData();
  }, []);
  
  useEffect(() => {
    if (activeTab === 'audit') {
      loadAuditLogs();
    }
    if (activeTab === 'mfa') {
      loadMfaUsers();
    }
    if (activeTab === 'departments' || activeTab === 'navigation' || activeTab === 'visibility' || activeTab === 'users') {
      loadDeptNavData();
    }
    if (activeTab === 'visibility') {
      loadVisibilityMatrix();
    }
  }, [activeTab, auditFilters]);

  const loadMfaUsers = async () => {
    setMfaLoading(true); setMfaMsg('');
    try {
      const token = localStorage.getItem('auth_token');
      const res = await fetch(`${API_BASE}/auth/mfa/users`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error('Failed to load MFA users');
      const data: MFAUserEntry[] = await res.json();
      setMfaUsers(data);
    } catch (e: any) {
      setMfaMsg(`⚠️ ${e.message}`);
    } finally {
      setMfaLoading(false);
    }
  };

  const loadDeptNavData = async () => {
    const token = localStorage.getItem('auth_token');
    const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
    try {
      const [dRes, gRes, iRes] = await Promise.all([
        fetch(`${API_BASE}/api/departments`, { headers }),
        fetch(`${API_BASE}/api/nav/groups`, { headers }),
        fetch(`${API_BASE}/api/nav/items`, { headers }),
      ]);
      if (dRes.ok) setDepartments(await dRes.json());
      if (gRes.ok) setNavGroups(await gRes.json());
      if (iRes.ok) setNavItems(await iRes.json());
    } catch (e) { console.warn('Failed to load dept/nav data', e); }
  };

  const loadVisibilityMatrix = async () => {
    const token = localStorage.getItem('auth_token');
    try {
      const res = await fetch(`${API_BASE}/api/departments/visibility/matrix`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setVisibilityMatrix(data);
        // Initialize visEdits from matrix
        const edits: Record<number, { groups: Set<number>; items: Set<number> }> = {};
        for (const d of data.departments) {
          edits[d.id] = { groups: new Set<number>(), items: new Set<number>() };
        }
        for (const link of data.department_group_visibility) {
          if (edits[link.department_id]) edits[link.department_id].groups.add(link.nav_group_id);
        }
        for (const link of data.department_item_visibility) {
          if (edits[link.department_id]) edits[link.department_id].items.add(link.nav_item_id);
        }
        setVisEdits(edits);
      }
    } catch (e) { console.warn('Failed to load visibility matrix', e); }
  };

  const handleCreateDepartment = async () => {
    if (!deptForm.name.trim()) return;
    const token = localStorage.getItem('auth_token');
    setDeptMsg('');
    try {
      const res = await fetch(`${API_BASE}/api/departments`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(deptForm),
      });
      if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || `HTTP ${res.status}`); }
      setDeptMsg('✅ Department created');
      setDeptForm({ name: '', description: '', sort_order: 0 });
      loadDeptNavData();
      setTimeout(() => setDeptMsg(''), 3000);
    } catch (e: any) { setDeptMsg(`⚠️ ${e.message}`); }
  };

  const handleDeleteDepartment = async (id: number) => {
    if (!confirm('Delete this department?')) return;
    const token = localStorage.getItem('auth_token');
    setDeptMsg('');
    try {
      const res = await fetch(`${API_BASE}/api/departments/${id}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || `HTTP ${res.status}`); }
      setDeptMsg('✅ Department deleted');
      loadDeptNavData();
      setTimeout(() => setDeptMsg(''), 3000);
    } catch (e: any) { setDeptMsg(`⚠️ ${e.message}`); }
  };

  const handleSaveVisibility = async (deptId: number) => {
    const token = localStorage.getItem('auth_token');
    setVisMsg('');
    const edit = visEdits[deptId];
    if (!edit) return;
    try {
      const res = await fetch(`${API_BASE}/api/departments/${deptId}/visibility`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          nav_group_ids: Array.from(edit.groups),
          nav_item_ids: Array.from(edit.items),
        }),
      });
      if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || `HTTP ${res.status}`); }
      setVisMsg(`✅ Visibility saved for department`);
      setTimeout(() => setVisMsg(''), 3000);
    } catch (e: any) { setVisMsg(`⚠️ ${e.message}`); }
  };

  const toggleVisGroup = (deptId: number, groupId: number) => {
    setVisEdits(prev => {
      const copy = { ...prev };
      const entry = { groups: new Set(copy[deptId]?.groups || []), items: new Set(copy[deptId]?.items || []) };
      if (entry.groups.has(groupId)) {
        entry.groups.delete(groupId);
        // Also remove all items in this group
        navItems.filter(i => i.nav_group_id === groupId).forEach(i => entry.items.delete(i.id));
      } else {
        entry.groups.add(groupId);
        // Also add all items in this group
        navItems.filter(i => i.nav_group_id === groupId).forEach(i => entry.items.add(i.id));
      }
      copy[deptId] = entry;
      return copy;
    });
  };

  const toggleVisItem = (deptId: number, itemId: number) => {
    setVisEdits(prev => {
      const copy = { ...prev };
      const entry = { groups: new Set(copy[deptId]?.groups || []), items: new Set(copy[deptId]?.items || []) };
      if (entry.items.has(itemId)) {
        entry.items.delete(itemId);
      } else {
        entry.items.add(itemId);
      }
      copy[deptId] = entry;
      return copy;
    });
  };

  // ── Navigation Group CRUD ──
  const handleCreateGroup = async () => {
    if (!groupForm.key.trim() || !groupForm.label.trim()) { setNavMsg('⚠️ Key and Label required'); return; }
    const token = localStorage.getItem('auth_token');
    setNavMsg('');
    try {
      const res = await fetch(`${API_BASE}/api/nav/groups`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(groupForm),
      });
      if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || `HTTP ${res.status}`); }
      setNavMsg('✅ Group created');
      setGroupForm({ key: '', label: '', icon: '', description: '', sort_order: 0, is_default: false });
      loadDeptNavData();
      setTimeout(() => setNavMsg(''), 3000);
    } catch (e: any) { setNavMsg(`⚠️ ${e.message}`); }
  };

  const handleUpdateGroup = async (groupId: number) => {
    const token = localStorage.getItem('auth_token');
    setNavMsg('');
    try {
      const res = await fetch(`${API_BASE}/api/nav/groups/${groupId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(groupForm),
      });
      if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || `HTTP ${res.status}`); }
      setNavMsg('✅ Group updated');
      setEditingGroupId(null);
      setGroupForm({ key: '', label: '', icon: '', description: '', sort_order: 0, is_default: false });
      loadDeptNavData();
      setTimeout(() => setNavMsg(''), 3000);
    } catch (e: any) { setNavMsg(`⚠️ ${e.message}`); }
  };

  const handleDeleteGroup = async (groupId: number) => {
    if (!confirm('Delete this navigation group and all its items?')) return;
    const token = localStorage.getItem('auth_token');
    setNavMsg('');
    try {
      const res = await fetch(`${API_BASE}/api/nav/groups/${groupId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || `HTTP ${res.status}`); }
      setNavMsg('✅ Group deleted');
      loadDeptNavData();
      setTimeout(() => setNavMsg(''), 3000);
    } catch (e: any) { setNavMsg(`⚠️ ${e.message}`); }
  };

  const startEditGroup = (group: any) => {
    setEditingGroupId(group.id);
    setGroupForm({ key: group.key, label: group.label, icon: group.icon || '', description: group.description || '', sort_order: group.sort_order, is_default: group.is_default || false });
  };

  // ── Navigation Item CRUD ──
  const handleCreateItem = async () => {
    if (!itemForm.key.trim() || !itemForm.label.trim() || !itemForm.nav_group_id) {
      setNavMsg('⚠️ Key, Label and Group required'); return;
    }
    const token = localStorage.getItem('auth_token');
    setNavMsg('');
    try {
      const res = await fetch(`${API_BASE}/api/nav/items`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(itemForm),
      });
      if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || `HTTP ${res.status}`); }
      setNavMsg('✅ Item created');
      setItemForm({ key: '', label: '', icon: '', route: '', resource_key: '', nav_group_id: 0, sort_order: 0 });
      setShowAddItem(null);
      loadDeptNavData();
      setTimeout(() => setNavMsg(''), 3000);
    } catch (e: any) { setNavMsg(`⚠️ ${e.message}`); }
  };

  const handleUpdateItem = async (itemId: number) => {
    const token = localStorage.getItem('auth_token');
    setNavMsg('');
    try {
      const res = await fetch(`${API_BASE}/api/nav/items/${itemId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(itemForm),
      });
      if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || `HTTP ${res.status}`); }
      setNavMsg('✅ Item updated');
      setEditingItemId(null);
      setItemForm({ key: '', label: '', icon: '', route: '', resource_key: '', nav_group_id: 0, sort_order: 0, is_active: true, is_action: false });
      loadDeptNavData();
      setTimeout(() => setNavMsg(''), 3000);
    } catch (e: any) { setNavMsg(`⚠️ ${e.message}`); }
  };

  const handleDeleteItem = async (itemId: number) => {
    if (!confirm('Delete this navigation item?')) return;
    const token = localStorage.getItem('auth_token');
    setNavMsg('');
    try {
      const res = await fetch(`${API_BASE}/api/nav/items/${itemId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || `HTTP ${res.status}`); }
      setNavMsg('✅ Item deleted');
      loadDeptNavData();
      setTimeout(() => setNavMsg(''), 3000);
    } catch (e: any) { setNavMsg(`⚠️ ${e.message}`); }
  };

  const handleMoveItem = async (itemId: number, newGroupId: number) => {
    const token = localStorage.getItem('auth_token');
    const item = navItems.find((i: any) => i.id === itemId);
    if (!item) return;
    try {
      await fetch(`${API_BASE}/api/nav/items/${itemId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ ...item, nav_group_id: newGroupId }),
      });
      setNavMsg('✅ Item moved');
      loadDeptNavData();
      setTimeout(() => setNavMsg(''), 3000);
    } catch (e: any) { setNavMsg(`⚠️ ${e.message}`); }
  };

  const startEditItem = (item: any) => {
    setEditingItemId(item.id);
    setItemForm({
      key: item.key, label: item.label, icon: item.icon || '',
      route: item.route || '', resource_key: item.resource_key || '',
      nav_group_id: item.nav_group_id, sort_order: item.sort_order,
      is_active: item.is_active !== false, is_action: !!item.is_action,
    });
  };

  // Inline sort_order update for items (no need to enter full edit mode)
  const handleUpdateItemSortOrder = async (itemId: number, newOrder: number) => {
    const token = localStorage.getItem('auth_token');
    try {
      await fetch(`${API_BASE}/api/nav/items/${itemId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ sort_order: newOrder }),
      });
      loadDeptNavData();
    } catch (e: any) { setNavMsg(`⚠️ ${e.message}`); }
  };

  // Set a group as the default (auto-open on login)
  const handleSetDefaultGroup = async (groupId: number) => {
    const token = localStorage.getItem('auth_token');
    setNavMsg('');
    try {
      const res = await fetch(`${API_BASE}/api/nav/groups/${groupId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ is_default: true }),
      });
      if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || `HTTP ${res.status}`); }
      setNavMsg('✅ Default group updated — this group will auto-open on login');
      loadDeptNavData();
      setTimeout(() => setNavMsg(''), 4000);
    } catch (e: any) { setNavMsg(`⚠️ ${e.message}`); }
  };

  const handleSetUserDepartment = async (username: string, departmentId: number | null) => {
    const token = localStorage.getItem('auth_token');
    try {
      const res = await fetch(`${API_BASE}/api/auth/users/${username}/department`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ department_id: departmentId }),
      });
      if (res.ok) {
        loadData();
      }
    } catch (e) { console.warn('Failed to set department', e); }
  };

  const loadData = async () => {
    setLoading(true);
    setError('');
    try {
      // Get auth token from localStorage if available
      const token = localStorage.getItem('auth_token');
      const headers = token ? { 
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
      } : { 'Content-Type': 'application/json' };
      
      // Load real users from LDAP via API
      try {
        const usersResponse = await fetch(`${API_BASE}/auth/users`, { headers });
        if (usersResponse.ok) {
          const usersData = await usersResponse.json();
          setUsers(usersData);
        } else {
          console.warn('Could not load users from API');
          setUsers([]);
        }
      } catch (err) {
        console.warn('Users API not available:', err);
        setUsers([]);
      }
      
      // Load role definitions
      try {
        const rolesResponse = await fetch(`${API_BASE}/auth/roles`, { headers });
        if (rolesResponse.ok) {
          const rolesData = await rolesResponse.json();
          setRoles(rolesData);
        } else {
          throw new Error('Roles API not available');
        }
      } catch (err) {
        console.warn('Roles API not available:', err);
        // Fallback to basic roles
        setRoles([
          { id: 1, name: 'superadmin', description: 'Full system access', userCount: users.filter(u => u.role === 'superadmin').length },
          { id: 2, name: 'admin', description: 'Administrative access', userCount: users.filter(u => u.role === 'admin').length },
          { id: 3, name: 'technical', description: 'Technical access — read all, create tenants/orgs, no delete', userCount: users.filter(u => u.role === 'technical').length },
          { id: 4, name: 'operator', description: 'Operational access', userCount: users.filter(u => u.role === 'operator').length },
          { id: 5, name: 'viewer', description: 'Read-only access', userCount: users.filter(u => u.role === 'viewer').length }
        ]);
      }
      
      // Load permissions
      try {
        const permissionsResponse = await fetch(`${API_BASE}/auth/permissions`, { headers });
        if (permissionsResponse.ok) {
          const permissionsData = await permissionsResponse.json();
          setPermissions(permissionsData);
        } else {
          throw new Error('Permissions API not available');
        }
      } catch (err) {
        console.warn('Permissions API not available:', err);
        // Fallback to basic permissions matching actual UI resources
        setPermissions([
          { id: 1, resource: 'servers', action: 'read', roles: ['viewer', 'operator', 'technical', 'admin', 'superadmin'] },
          { id: 2, resource: 'servers', action: 'admin', roles: ['admin', 'superadmin'] },
          { id: 3, resource: 'volumes', action: 'read', roles: ['viewer', 'operator', 'technical', 'admin', 'superadmin'] },
          { id: 4, resource: 'volumes', action: 'admin', roles: ['admin', 'superadmin'] },
          { id: 5, resource: 'snapshots', action: 'read', roles: ['viewer', 'operator', 'technical', 'admin', 'superadmin'] },
          { id: 6, resource: 'snapshots', action: 'write', roles: ['technical', 'admin', 'superadmin'] },
          { id: 7, resource: 'networks', action: 'read', roles: ['viewer', 'operator', 'technical', 'admin', 'superadmin'] },
          { id: 8, resource: 'networks', action: 'write', roles: ['operator', 'technical', 'admin', 'superadmin'] },
          { id: 9, resource: 'users', action: 'admin', roles: ['superadmin'] },
          { id: 10, resource: 'monitoring', action: 'read', roles: ['viewer', 'operator', 'technical', 'admin', 'superadmin'] },
          { id: 11, resource: 'hypervisors', action: 'read', roles: ['viewer', 'operator', 'technical', 'admin', 'superadmin'] },
          { id: 12, resource: 'flavors', action: 'read', roles: ['viewer', 'operator', 'technical', 'admin', 'superadmin'] },
          { id: 13, resource: 'flavors', action: 'write', roles: ['operator', 'technical', 'admin', 'superadmin'] },
          { id: 14, resource: 'restore', action: 'read', roles: ['viewer', 'operator', 'technical', 'admin', 'superadmin'] },
          { id: 15, resource: 'restore', action: 'write', roles: ['admin', 'superadmin'] },
          { id: 16, resource: 'restore', action: 'admin', roles: ['superadmin'] },
          { id: 17, resource: 'reports', action: 'read', roles: ['viewer', 'operator', 'technical', 'admin', 'superadmin'] },
          { id: 18, resource: 'resources', action: 'read', roles: ['viewer', 'operator', 'technical', 'admin', 'superadmin'] },
          { id: 19, resource: 'resources', action: 'write', roles: ['technical', 'admin', 'superadmin'] },
          { id: 20, resource: 'provisioning', action: 'read', roles: ['viewer', 'operator', 'technical', 'admin', 'superadmin'] },
          { id: 21, resource: 'provisioning', action: 'write', roles: ['technical', 'admin', 'superadmin'] },
          { id: 22, resource: 'metering', action: 'read', roles: ['viewer', 'operator', 'technical', 'admin', 'superadmin'] },
          { id: 23, resource: 'notifications', action: 'read', roles: ['viewer', 'operator', 'technical', 'admin', 'superadmin'] },
          { id: 24, resource: 'backup', action: 'read', roles: ['viewer', 'operator', 'technical', 'admin', 'superadmin'] },
          { id: 25, resource: 'dashboard', action: 'read', roles: ['viewer', 'operator', 'technical', 'admin', 'superadmin'] },
          { id: 26, resource: 'branding', action: 'read', roles: ['viewer', 'operator', 'technical', 'admin', 'superadmin'] }
        ]);
      }
    } catch (error) {
      console.error('Error loading data:', error);
      setError('Failed to connect to authentication server');
    } finally {
      setLoading(false);
    }
  };

  const handleAddUser = async (userData) => {
    try {
      const token = localStorage.getItem('auth_token');
      const response = await fetch(`${API_BASE}/auth/users`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify(userData)
      });
      
      if (response.ok) {
        // If department was selected, assign it right after creation
        if (userData.department_id) {
          try {
            await fetch(`${API_BASE}/api/auth/users/${userData.username}/department`, {
              method: 'PUT',
              headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
              body: JSON.stringify({ department_id: Number(userData.department_id) })
            });
          } catch (deptErr) {
            console.warn('User created but department assignment failed:', deptErr);
          }
        }
        await loadData(); // Refresh data
        setShowModal(false);
        setFormData({});
      } else {
        const errorData = await response.json();
        setError(errorData.detail || 'Failed to create user');
      }
    } catch (err) {
      console.error('Error creating user:', err);
      setError('Failed to create user');
    }
  };

  const handleUpdateUserRole = async (userData) => {
    try {
      const token = localStorage.getItem('auth_token');

      // 1. Update role
      const response = await fetch(`${API_BASE}/auth/users/${userData.username}/role`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          username: userData.username,
          role: userData.role
        })
      });

      if (!response.ok) {
        const errorData = await response.json();
        setError(errorData.detail || 'Failed to update user role');
        return;
      }

      // 2. Update department if changed
      const currentDeptId = editingItem?.department_id ? String(editingItem.department_id) : '';
      const newDeptId = userData.department_id ? String(userData.department_id) : '';
      if (newDeptId !== currentDeptId) {
        await handleSetUserDepartment(userData.username, newDeptId ? Number(newDeptId) : null);
      }

      await loadData();
      setShowModal(false);
      setEditingItem(null);
    } catch (err) {
      console.error('Error updating user:', err);
      setError('Failed to update user');
    }
  };

  const handleDeleteUser = async (userId) => {
    if (!confirm('Are you sure you want to delete this user?')) return;
    
    try {
      const token = localStorage.getItem('auth_token');
      const response = await fetch(`${API_BASE}/auth/users/${userId}`, {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });
      
      if (response.ok) {
        await loadData(); // Refresh data
      } else {
        const errorData = await response.json();
        setError(errorData.detail || 'Failed to delete user');
      }
    } catch (err) {
      console.error('Error deleting user:', err);
      setError('Failed to delete user');
    }
  };
  
  const loadAuditLogs = async () => {
    try {
      const token = localStorage.getItem('auth_token');
      const params = new URLSearchParams();
      
      if (auditFilters.username) params.append('username', auditFilters.username);
      if (auditFilters.action) params.append('action', auditFilters.action);
      if (auditFilters.startDate) params.append('start_date', auditFilters.startDate);
      if (auditFilters.endDate) params.append('end_date', auditFilters.endDate);
      
      const response = await fetch(`${API_BASE}/auth/audit?${params.toString()}`, {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });
      
      if (response.ok) {
        const data = await response.json();
        setAuditLogs(data);
      } else {
        console.error('Failed to load audit logs');
        setAuditLogs([]);
      }
    } catch (err) {
      console.error('Error loading audit logs:', err);
      setAuditLogs([]);
    }
  };

  const UserForm = ({ user, onSave, onCancel }) => {
    const [localFormData, setLocalFormData] = useState({
      username: user?.username || '',
      email: user?.email || '',
      role: user?.role || 'superadmin',
      password: '',
      confirmPassword: '',
      status: user?.status || 'active',
      department_id: user?.department_id || ''
    });

    const handleSubmit = (e) => {
      e.preventDefault();
      if (localFormData.password !== localFormData.confirmPassword) {
        alert('Passwords do not match');
        return;
      }
      onSave(localFormData);
    };

    return (
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-sm font-medium mb-1">Username</label>
          <input
            type="text"
            value={localFormData.username}
            onChange={(e) => setLocalFormData({...localFormData, username: e.target.value})}
            className="w-full p-2 border rounded"
            required
            disabled={!!user}
            style={user ? { opacity: 0.6, cursor: 'not-allowed' } : {}}
          />
          {user && <span className="text-xs text-gray-500">Username cannot be changed</span>}
        </div>
        <div>
          <label className="block text-sm font-medium mb-1">Email</label>
          <input
            type="email"
            value={localFormData.email}
            onChange={(e) => setLocalFormData({...localFormData, email: e.target.value})}
            className="w-full p-2 border rounded"
            required={!user}
            disabled={!!user}
            style={user ? { opacity: 0.6, cursor: 'not-allowed' } : {}}
          />
          {user && <span className="text-xs text-gray-500">Managed via LDAP</span>}
        </div>
        <div>
          <label className="block text-sm font-medium mb-1">Role</label>
          <select
            value={localFormData.role}
            onChange={(e) => setLocalFormData({...localFormData, role: e.target.value})}
            className="w-full p-2 border rounded"
          >
            {roles.map(role => (
              <option key={role.id} value={role.name}>{role.name}</option>
            ))}
          </select>
        </div>
        {!user && (
          <>
            <div>
              <label className="block text-sm font-medium mb-1">Password</label>
              <input
                type="password"
                value={localFormData.password}
                onChange={(e) => setLocalFormData({...localFormData, password: e.target.value})}
                className="w-full p-2 border rounded"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Confirm Password</label>
              <input
                type="password"
                value={localFormData.confirmPassword}
                onChange={(e) => setLocalFormData({...localFormData, confirmPassword: e.target.value})}
                className="w-full p-2 border rounded"
                required
              />
            </div>
          </>
        )}
        <div>
          <label className="block text-sm font-medium mb-1">Status</label>
          <select
            value={localFormData.status}
            onChange={(e) => setLocalFormData({...localFormData, status: e.target.value})}
            className="w-full p-2 border rounded"
          >
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
            <option value="suspended">Suspended</option>
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium mb-1">Department</label>
          <select
            value={localFormData.department_id}
            onChange={(e) => setLocalFormData({...localFormData, department_id: e.target.value})}
            className="w-full p-2 border rounded"
          >
            <option value="">— No department —</option>
            {departments.map((dept: any) => (
              <option key={dept.id} value={dept.id}>{dept.name}</option>
            ))}
          </select>
        </div>
        <div className="flex justify-end space-x-2">
          <button
            type="button"
            onClick={onCancel}
            className="px-4 py-2 text-gray-600 border rounded hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            type="submit"
            className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
          >
            {user ? 'Update' : 'Create'} User
          </button>
        </div>
      </form>
    );
  };

  const PermissionMatrix = () => {
    // Resource descriptions for human-readable display
    const resourceDescriptions: Record<string, string> = {
      api_metrics: 'API Performance Metrics — latency, error rates, request stats',
      audit: 'Compliance Audit — audit logs, change analysis, accountability',
      backup: 'Database Backup — scheduling, history, restore from backup',
      branding: 'Portal Branding — logo, colors, theme customization',
      dashboard: 'Landing Dashboard — system overview, KPIs, quick stats',
      departments: 'Departments — organizational units for user grouping',
      domains: 'OpenStack Domains — organizational boundaries (tenants/projects)',
      drift: 'Configuration Drift — detect field-level changes across resources',
      flavors: 'VM Flavors — CPU, RAM, disk definitions for VMs',
      floatingips: 'Floating IPs — external connectivity, NAT mappings',
      history: 'Change History — infrastructure change timeline & audit trail',
      hypervisors: 'Hypervisors — compute nodes, resource utilization',
      images: 'Glance Images — VM templates, OS images',
      metering: 'Operational Metering — resource usage, chargeback, efficiency',
      mfa: 'Multi-Factor Authentication — TOTP setup, enforcement',
      monitoring: 'Real-time Monitoring — VM/host metrics, resource alerts',
      navigation: 'Navigation Catalog — nav groups, items, menu structure',
      networks: 'Neutron Networks — virtual networks, provider/tenant',
      notifications: 'Email Notifications — preferences, SMTP, delivery history',
      ports: 'Neutron Ports — network interfaces, IP assignments',
      projects: 'OpenStack Projects — tenant workspaces, quota containers',
      provisioning: 'Customer Provisioning — domain setup, quotas, onboarding',
      reports: 'Reports — generated reports, exports, analytics',
      resources: 'Resource Management — allocation, capacity, assignments',
      restore: 'Snapshot Restore — restore wizard, execution, monitoring',
      security_groups: 'Security Groups — firewall rules, VM associations',
      servers: 'VMs / Servers — virtual machines, Nova instances',
      snapshots: 'Volume Snapshots — retention, compliance, policies',
      subnets: 'Subnets — IP ranges within networks, DHCP settings',
      system_logs: 'System Logs — activity log, diagnostics, central audit',
      tenant_health: 'Tenant Health — health scores, risk assessment, status',
      users: 'User Management — LDAP users, roles, access control',
      volumes: 'Block Storage — Cinder volumes, disks attached to VMs',
    };
    const actionDescriptions: Record<string, string> = {
      read: 'View',
      write: 'Create / Edit',
      admin: 'Full control (delete, configure)',
      resource_delete: 'Delete resources',
      tenant_delete: 'Delete tenants',
      tenant_disable: 'Disable tenants',
    };

    // Sort permissions by resource, then action
    const baseSorted = [...permissions].sort((a, b) => {
      if (a.resource !== b.resource) return a.resource.localeCompare(b.resource);
      return a.action.localeCompare(b.action);
    });

    // Group by resource for row-spanning
    const allResourceGroups: { resource: string; perms: typeof baseSorted }[] = [];
    let lastRes = '';
    for (const p of baseSorted) {
      if (p.resource !== lastRes) {
        allResourceGroups.push({ resource: p.resource, perms: [p] });
        lastRes = p.resource;
      } else {
        allResourceGroups[allResourceGroups.length - 1].perms.push(p);
      }
    }

    // Filter by search query
    const query = permSearchQuery.toLowerCase().trim();
    const searchFiltered = query
      ? allResourceGroups.filter(g =>
          g.resource.toLowerCase().includes(query) ||
          (resourceDescriptions[g.resource] || '').toLowerCase().includes(query) ||
          g.perms.some(p => (actionDescriptions[p.action] || p.action).toLowerCase().includes(query))
        )
      : allResourceGroups;

    // Sort groups
    const filteredGroups = [...searchFiltered].sort((a, b) => {
      let cmp = 0;
      if (permSortBy === 'resource') {
        cmp = a.resource.localeCompare(b.resource);
      } else if (permSortBy === 'action') {
        cmp = a.perms.length - b.perms.length;
      } else if (permSortBy === 'roles') {
        const aRoles = a.perms.reduce((sum, p) => sum + p.roles.length, 0);
        const bRoles = b.perms.reduce((sum, p) => sum + p.roles.length, 0);
        cmp = aRoles - bRoles;
      }
      return permSortDir === 'asc' ? cmp : -cmp;
    });
    
    return (
      <div className="overflow-x-auto">
        {/* Search + Sort controls */}
        <div className="flex items-center gap-4 mb-3">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium">🔍</span>
            <input
              type="text"
              placeholder="Search resources or descriptions..."
              value={permSearchQuery}
              onChange={(e) => setPermSearchQuery(e.target.value)}
              className="px-3 py-1.5 border rounded text-sm"
              style={{ minWidth: '280px' }}
            />
            {permSearchQuery && (
              <button
                onClick={() => setPermSearchQuery('')}
                className="text-xs text-gray-500 hover:text-gray-700 px-1"
                title="Clear search"
              >✕</button>
            )}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium">Sort:</span>
            <select
              value={permSortBy}
              onChange={(e) => setPermSortBy(e.target.value as 'resource' | 'action' | 'roles')}
              className="px-2 py-1.5 border rounded text-sm"
            >
              <option value="resource">Resource</option>
              <option value="action">Action</option>
              <option value="roles">Role Count</option>
            </select>
            <button
              onClick={() => setPermSortDir(d => d === 'asc' ? 'desc' : 'asc')}
              className="px-2 py-1 border rounded text-sm hover:bg-gray-100"
              title={`Sort ${permSortDir === 'asc' ? 'descending' : 'ascending'}`}
            >
              {permSortDir === 'asc' ? '▲' : '▼'}
            </button>
          </div>
          <span className="text-xs text-gray-500 ml-auto">
            {filteredGroups.length} of {allResourceGroups.length} resources
          </span>
        </div>
        <style>{`
          .permission-checkbox {
            appearance: none;
            -webkit-appearance: none;
            -moz-appearance: none;
            width: 16px;
            height: 16px;
            border: 2px solid #4b5563;
            border-radius: 3px;
            background-color: #1a1f2e;
            cursor: pointer;
            transition: all 0.2s ease;
          }
          .permission-checkbox:checked {
            background-color: #3b82f6;
            border-color: #3b82f6;
          }
          .permission-checkbox:checked::after {
            content: '\\2713';
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: bold;
            font-size: 12px;
          }
          .permission-checkbox:disabled {
            cursor: not-allowed;
            opacity: 0.8;
          }
        `}</style>
        <table className="w-full border-collapse border border-gray-300" style={{ fontSize: '0.85rem' }}>
          <thead>
            <tr>
              <th className="border border-gray-300 p-2 bg-gray-100 text-left cursor-pointer select-none"
                style={{ minWidth: '160px' }}
                onClick={() => { setPermSortBy('resource'); setPermSortDir(d => permSortBy === 'resource' ? (d === 'asc' ? 'desc' : 'asc') : 'asc'); }}>
                Resource {permSortBy === 'resource' ? (permSortDir === 'asc' ? '▲' : '▼') : ''}
              </th>
              <th className="border border-gray-300 p-2 bg-gray-100 text-left" style={{ minWidth: '240px' }}>Description</th>
              <th className="border border-gray-300 p-2 bg-gray-100 text-left cursor-pointer select-none"
                style={{ width: '100px' }}
                onClick={() => { setPermSortBy('action'); setPermSortDir(d => permSortBy === 'action' ? (d === 'asc' ? 'desc' : 'asc') : 'asc'); }}>
                Action {permSortBy === 'action' ? (permSortDir === 'asc' ? '▲' : '▼') : ''}
              </th>
              {roles.map(role => (
                <th key={role.id} className="border border-gray-300 p-2 bg-gray-100 text-center" style={{ width: '90px' }}>{role.name}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filteredGroups.length === 0 && (
              <tr><td colSpan={3 + roles.length} className="text-center text-gray-400 p-4">No matching resources found</td></tr>
            )}
            {filteredGroups.map(group => (
              group.perms.map((permission, pidx) => (
                <tr key={`${permission.resource}-${permission.action}`}
                  style={{ borderTop: pidx === 0 ? '2px solid #d1d5db' : undefined }}>
                  {pidx === 0 && (
                    <>
                      <td className="border border-gray-300 p-2 font-semibold align-top" rowSpan={group.perms.length}
                        style={{ background: '#f9fafb' }}>
                        {group.resource}
                      </td>
                      <td className="border border-gray-300 p-2 text-gray-500 align-top text-xs" rowSpan={group.perms.length}
                        style={{ background: '#f9fafb' }}>
                        {resourceDescriptions[group.resource] || group.resource}
                      </td>
                    </>
                  )}
                  <td className="border border-gray-300 p-2">
                    <span title={actionDescriptions[permission.action] || permission.action}>
                      {actionDescriptions[permission.action] || permission.action}
                    </span>
                  </td>
                  {roles.map(role => (
                    <td key={role.id} className="border border-gray-300 p-2 text-center">
                      <input
                        type="checkbox"
                        checked={permission.roles.includes(role.name)}
                        onChange={() => {
                          console.log(`Toggle ${permission.resource}:${permission.action} for ${role.name}`);
                        }}
                        className="permission-checkbox"
                        disabled={true}
                      />
                    </td>
                  ))}
                </tr>
              ))
            ))}
          </tbody>
        </table>
      </div>
    );
  };

  if (loading) {
    return (
      <div className="p-6">
        <div className="flex items-center justify-center h-64">
          <span>Loading authentication users...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold">Authentication Management</h1>
        <div className="flex space-x-2">
          <p className="text-gray-600 text-sm">Manage LDAP users for accessing this management system</p>
        </div>
        <div className="flex space-x-2">
          <button
            onClick={loadData}
            className="flex items-center px-3 py-2 text-gray-600 border rounded hover:bg-gray-50"
          >
            🔄 Refresh
          </button>
          {activeTab === 'users' && (
            <button
              onClick={() => {
                setModalType('user');
                setEditingItem(null);
                setShowModal(true);
              }}
              className="flex items-center px-3 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
            >
              ➕ Add User
            </button>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b mb-6" style={{ flexWrap: 'wrap' }}>
        {[
          { id: 'users', label: 'LDAP Users', icon: '👥', adminOnly: true },
          { id: 'roles', label: 'Roles', icon: '🛡️', adminOnly: true },
          { id: 'permissions', label: 'Permissions', icon: '🔑', adminOnly: true },
          { id: 'departments', label: 'Departments', icon: '🏢', adminOnly: true },
          { id: 'navigation', label: 'Navigation', icon: '🗂️', adminOnly: true },
          { id: 'visibility', label: 'Visibility', icon: '👁️', adminOnly: true },
          { id: 'mfa', label: 'MFA', icon: '🔐', adminOnly: true },
          { id: 'audit', label: 'System Audit', icon: '📋', adminOnly: false },
          { id: 'branding', label: 'Branding', icon: '🎨', adminOnly: true }
        ]
          .filter(tab => !tab.adminOnly || (user && (user.role === 'admin' || user.role === 'superadmin')))
          .map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex items-center px-4 py-2 border-b-2 ${
              activeTab === tab.id 
                ? 'border-blue-600 text-blue-600' 
                : 'border-transparent text-gray-600 hover:text-gray-900'
            }`}
          >
            <span className="mr-2">{tab.icon}</span>
            {tab.label}
          </button>
        ))}
      </div>

      {/* Content */}
      {activeTab === 'users' && (
        <div className="bg-white rounded-lg border">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-sm font-medium text-gray-900">Username</th>
                  <th className="px-4 py-3 text-left text-sm font-medium text-gray-900">Email</th>
                  <th className="px-4 py-3 text-left text-sm font-medium text-gray-900">Role</th>
                  <th className="px-4 py-3 text-left text-sm font-medium text-gray-900">Department</th>
                  <th className="px-4 py-3 text-left text-sm font-medium text-gray-900">Status</th>
                  <th className="px-4 py-3 text-left text-sm font-medium text-gray-900">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {users.map(user => (
                  <tr key={user.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-sm">{user.username}</td>
                    <td className="px-4 py-3 text-sm">{user.email}</td>
                    <td className="px-4 py-3 text-sm">
                      <span className={`px-2 py-1 text-xs rounded-full ${
                        user.role === 'superadmin' ? 'bg-red-100 text-red-800' :
                        user.role === 'admin' ? 'bg-blue-100 text-blue-800' :
                        user.role === 'operator' ? 'bg-green-100 text-green-800' :
                        'bg-gray-100 text-gray-800'
                      }`}>
                        {user.role}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm">
                      <select
                        value={user.department_id || ''}
                        onChange={(e) => handleSetUserDepartment(user.username, e.target.value ? Number(e.target.value) : null)}
                        className="px-2 py-1 border rounded text-xs"
                        style={{ minWidth: '120px' }}
                      >
                        <option value="">— None —</option>
                        {departments.map(d => (
                          <option key={d.id} value={d.id}>{d.name}</option>
                        ))}
                      </select>
                    </td>
                    <td className="px-4 py-3 text-sm">
                      <span className={`px-2 py-1 text-xs rounded-full ${
                        user.status === 'active' ? 'bg-green-100 text-green-800' :
                        user.status === 'inactive' ? 'bg-gray-100 text-gray-800' :
                        'bg-red-100 text-red-800'
                      }`}>
                        {user.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm">
                      <div className="flex space-x-2">
                        <button
                          onClick={() => {
                            setEditingItem(user);
                            setModalType('user');
                            setShowModal(true);
                          }}
                          className="text-blue-600 hover:text-blue-900"
                        >
                          <span>✏️</span>
                        </button>
                        <button
                          onClick={() => handleDeleteUser(user.username)}
                          className="text-red-600 hover:text-red-900"
                        >
                          <span>🗑️</span>
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {activeTab === 'roles' && (
        <div className="bg-white rounded-lg border">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-sm font-medium text-gray-900">Role Name</th>
                  <th className="px-4 py-3 text-left text-sm font-medium text-gray-900">Description</th>
                  <th className="px-4 py-3 text-left text-sm font-medium text-gray-900">Users</th>
                  <th className="px-4 py-3 text-left text-sm font-medium text-gray-900">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {roles.map(role => (
                  <tr key={role.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-sm font-medium">{role.name}</td>
                    <td className="px-4 py-3 text-sm">{role.description}</td>
                    <td className="px-4 py-3 text-sm">{role.userCount}</td>
                    <td className="px-4 py-3 text-sm">
                      <button className="text-blue-600 hover:text-blue-900">
                        <span>✏️</span>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {activeTab === 'permissions' && (
        <div className="bg-white rounded-lg border p-6">
          <h3 className="text-lg font-medium mb-2">Permission Matrix</h3>
          <p className="text-sm text-gray-600 mb-4">
            This matrix shows which roles have access to each resource and action. Each resource maps to a feature area in the portal.
            <strong> read</strong> = View, <strong> write</strong> = Create/Edit, <strong> admin</strong> = Full control (delete, configure).
          </p>
          <PermissionMatrix />
        </div>
      )}

      {activeTab === 'audit' && (
        <div className="bg-white rounded-lg border">
          <div className="p-4 border-b bg-gray-50">
            <h3 className="text-lg font-medium mb-4">System Authentication Audit Log</h3>
            <p className="text-sm text-gray-600 mb-4">Track all authentication events (login, logout, user management). Logs retained for 90 days.</p>
            
            {/* Filters */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
              <input
                type="text"
                placeholder="Filter by username"
                value={auditFilters.username}
                onChange={(e) => setAuditFilters({...auditFilters, username: e.target.value})}
                className="px-3 py-2 border rounded text-sm"
              />
              <select
                value={auditFilters.action}
                onChange={(e) => setAuditFilters({...auditFilters, action: e.target.value})}
                className="px-3 py-2 border rounded text-sm"
              >
                <option value="">All Actions</option>
                <option value="login">Login</option>
                <option value="logout">Logout</option>
                <option value="failed_login">Failed Login</option>
                <option value="user_created">User Created</option>
                <option value="user_deleted">User Deleted</option>
                <option value="role_changed">Role Changed</option>
              </select>
              <input
                type="date"
                placeholder="Start Date"
                value={auditFilters.startDate}
                onChange={(e) => setAuditFilters({...auditFilters, startDate: e.target.value})}
                className="px-3 py-2 border rounded text-sm"
              />
              <input
                type="date"
                placeholder="End Date"
                value={auditFilters.endDate}
                onChange={(e) => setAuditFilters({...auditFilters, endDate: e.target.value})}
                className="px-3 py-2 border rounded text-sm"
              />
            </div>
            <div className="mt-3">
              <button
                onClick={loadAuditLogs}
                className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 text-sm"
              >
                Apply Filters
              </button>
              <button
                onClick={() => {
                  setAuditFilters({ username: '', action: '', startDate: '', endDate: '' });
                  loadAuditLogs();
                }}
                className="ml-2 px-4 py-2 bg-gray-200 text-gray-700 rounded hover:bg-gray-300 text-sm"
              >
                Clear Filters
              </button>
            </div>
          </div>
          
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-sm font-medium text-gray-900">Timestamp</th>
                  <th className="px-4 py-3 text-left text-sm font-medium text-gray-900">Username</th>
                  <th className="px-4 py-3 text-left text-sm font-medium text-gray-900">Action</th>
                  <th className="px-4 py-3 text-left text-sm font-medium text-gray-900">IP Address</th>
                  <th className="px-4 py-3 text-left text-sm font-medium text-gray-900">User Agent</th>
                  <th className="px-4 py-3 text-left text-sm font-medium text-gray-900">Status</th>
                  <th className="px-4 py-3 text-left text-sm font-medium text-gray-900">Details</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {auditLogs.length === 0 ? (
                  <tr>
                    <td colSpan="7" className="px-4 py-8 text-center text-gray-500">
                      No audit logs found
                    </td>
                  </tr>
                ) : (
                  auditLogs.map(log => (
                    <tr key={log.id} className="hover:bg-gray-50">
                      <td className="px-4 py-3 text-sm">
                        {new Date(log.timestamp).toLocaleString()}
                      </td>
                      <td className="px-4 py-3 text-sm font-medium">{log.username || 'N/A'}</td>
                      <td className="px-4 py-3 text-sm">
                        <span className={`px-2 py-1 rounded text-xs ${
                          log.action === 'login' ? 'bg-green-100 text-green-800' :
                          log.action === 'logout' ? 'bg-blue-100 text-blue-800' :
                          log.action === 'failed_login' ? 'bg-red-100 text-red-800' :
                          log.action === 'user_created' ? 'bg-purple-100 text-purple-800' :
                          log.action === 'user_deleted' ? 'bg-orange-100 text-orange-800' :
                          'bg-gray-100 text-gray-800'
                        }`}>
                          {log.action}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-sm">{log.ip_address || 'N/A'}</td>
                      <td className="px-4 py-3 text-sm text-xs max-w-xs truncate" title={log.user_agent}>
                        {log.user_agent || 'N/A'}
                      </td>
                      <td className="px-4 py-3 text-sm">
                        {log.success ? (
                          <span className="text-green-600">✓ Success</span>
                        ) : (
                          <span className="text-red-600">✗ Failed</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-sm">
                        {log.details && typeof log.details === 'object' ? (
                          <span className="text-xs text-gray-600" title={JSON.stringify(log.details, null, 2)}>
                            {Object.keys(log.details).length > 0 ? 'View details' : '-'}
                          </span>
                        ) : (
                          '-'
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Departments Tab ── */}
      {activeTab === 'departments' && (
        <div className="bg-white rounded-lg border p-6">
          <h3 className="text-lg font-medium mb-4">🏢 Departments</h3>
          <p className="text-sm text-gray-600 mb-4">
            Departments control which navigation groups and items are visible to users.
            Each user belongs to exactly one department.
          </p>
          {deptMsg && (
            <div style={{ padding: '8px 12px', borderRadius: '6px', marginBottom: '12px',
              background: deptMsg.startsWith('✅') ? '#dcfce7' : '#fee2e2',
              color: deptMsg.startsWith('✅') ? '#166534' : '#991b1b', fontSize: '0.85rem' }}>
              {deptMsg}
            </div>
          )}
          {/* Create form */}
          <div className="flex gap-2 mb-4" style={{ flexWrap: 'wrap' }}>
            <input type="text" placeholder="Department name" value={deptForm.name}
              onChange={e => setDeptForm(p => ({ ...p, name: e.target.value }))}
              className="px-3 py-2 border rounded text-sm" style={{ minWidth: '180px' }} />
            <input type="text" placeholder="Description (optional)" value={deptForm.description}
              onChange={e => setDeptForm(p => ({ ...p, description: e.target.value }))}
              className="px-3 py-2 border rounded text-sm" style={{ minWidth: '220px' }} />
            <input type="number" placeholder="Order" value={deptForm.sort_order}
              onChange={e => setDeptForm(p => ({ ...p, sort_order: Number(e.target.value) }))}
              className="px-3 py-2 border rounded text-sm" style={{ width: '80px' }} />
            <button onClick={handleCreateDepartment}
              className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 text-sm">
              ➕ Add
            </button>
          </div>
          {/* Table */}
          <table className="w-full">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-sm font-medium text-gray-900">Name</th>
                <th className="px-4 py-3 text-left text-sm font-medium text-gray-900">Description</th>
                <th className="px-4 py-3 text-left text-sm font-medium text-gray-900">Order</th>
                <th className="px-4 py-3 text-left text-sm font-medium text-gray-900">Active</th>
                <th className="px-4 py-3 text-left text-sm font-medium text-gray-900">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {departments.map(d => (
                <tr key={d.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm font-medium">{d.name}</td>
                  <td className="px-4 py-3 text-sm">{d.description || '—'}</td>
                  <td className="px-4 py-3 text-sm">{d.sort_order}</td>
                  <td className="px-4 py-3 text-sm">{d.is_active ? '✅' : '❌'}</td>
                  <td className="px-4 py-3 text-sm">
                    <button onClick={() => handleDeleteDepartment(d.id)}
                      className="text-red-600 hover:text-red-900 text-sm">🗑️ Delete</button>
                  </td>
                </tr>
              ))}
              {departments.length === 0 && (
                <tr><td colSpan={5} className="px-4 py-8 text-center text-gray-500">No departments yet</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* ── Navigation Catalog Tab ── */}
      {activeTab === 'navigation' && (
        <div className="bg-white rounded-lg border p-6">
          <h3 className="text-lg font-medium mb-2">🗂️ Navigation Catalog</h3>
          <p className="text-sm text-gray-600 mb-4">
            Manage navigation groups and items. You can create groups (e.g. "Main"), add items to groups,
            move items between groups, change sort order, and set a default group that auto-opens on login.
          </p>
          {navMsg && (
            <div style={{ padding: '8px 12px', borderRadius: '6px', marginBottom: '12px',
              background: navMsg.startsWith('✅') ? '#dcfce7' : '#fee2e2',
              color: navMsg.startsWith('✅') ? '#166534' : '#991b1b', fontSize: '0.85rem' }}>
              {navMsg}
            </div>
          )}

          {/* ═══════════════════════════════════════════════════════════════ */}
          {/* SECTION 1: Create / Edit Navigation Group                      */}
          {/* ═══════════════════════════════════════════════════════════════ */}
          <div style={{ border: '1px solid #e5e7eb', borderRadius: '8px', padding: '16px', marginBottom: '24px', background: '#f9fafb' }}>
            <h4 style={{ margin: '0 0 4px', fontSize: '1rem', fontWeight: 700, color: '#4338ca' }}>
              {editingGroupId ? '✏️ Edit Navigation Group' : '➕ Create New Navigation Group'}
            </h4>
            <p style={{ margin: '0 0 12px', fontSize: '0.8rem', color: '#6b7280' }}>
              {editingGroupId
                ? 'Modify the group properties below and click Save.'
                : 'Fill in the fields below to create a new first-layer navigation group (e.g. "Main"). The group appears as a pill in the top navigation bar.'}
            </p>

            {/* Row 1: Key, Label, Icon picker, Order, Default */}
            <div className="flex gap-2 mb-2" style={{ flexWrap: 'wrap', alignItems: 'center' }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                <label style={{ fontSize: '0.7rem', fontWeight: 600, color: '#374151' }}>Key</label>
                <input type="text" placeholder="e.g. main" value={groupForm.key}
                  onChange={e => setGroupForm(p => ({ ...p, key: e.target.value }))}
                  className="px-3 py-2 border rounded text-sm" style={{ width: '130px' }}
                  disabled={!!editingGroupId} />
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                <label style={{ fontSize: '0.7rem', fontWeight: 600, color: '#374151' }}>Label</label>
                <input type="text" placeholder="e.g. Main" value={groupForm.label}
                  onChange={e => setGroupForm(p => ({ ...p, label: e.target.value }))}
                  className="px-3 py-2 border rounded text-sm" style={{ width: '150px' }} />
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', position: 'relative' }}>
                <label style={{ fontSize: '0.7rem', fontWeight: 600, color: '#374151' }}>Icon</label>
                <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
                  <input type="text" placeholder="📦" value={groupForm.icon} readOnly
                    className="px-3 py-2 border rounded text-sm" style={{ width: '50px', cursor: 'pointer', textAlign: 'center', fontSize: '1.1rem' }}
                    onClick={() => setShowEmojiPicker(!showEmojiPicker)} />
                  <button type="button" onClick={() => setShowEmojiPicker(!showEmojiPicker)}
                    className="px-2 py-2 border rounded text-sm hover:bg-gray-100"
                    title="Pick an emoji icon">
                    🎨
                  </button>
                </div>
                {showEmojiPicker && (
                  <div style={{ position: 'absolute', top: '100%', left: 0, zIndex: 50, background: '#fff',
                    border: '1px solid #d1d5db', borderRadius: '8px', padding: '8px', boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
                    width: '280px', maxHeight: '200px', overflowY: 'auto' }}>
                    <p style={{ fontSize: '0.7rem', color: '#6b7280', margin: '0 0 6px' }}>Click an emoji to select it:</p>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                      {['📦','📋','📊','📈','📉','🗂️','🔧','⚙️','🛡️','🔒','🔑','👥','🏢','🏗️','💻','🖥️','📡','🌐','☁️','💾','💿','🗄️','📁','📂','📝','📄','🔍','🔎','🎯','⚡','🔔','📧','📮','✅','❌','⚠️','🚀','🔄','📌','🏷️','💰','📅','🕐','🗑️','✏️','➕','🎨','🧩','📱','🖨️'].map(emoji => (
                        <button key={emoji} type="button"
                          onClick={() => { setGroupForm(p => ({ ...p, icon: emoji })); setShowEmojiPicker(false); }}
                          style={{ width: '32px', height: '32px', display: 'flex', alignItems: 'center', justifyContent: 'center',
                            border: '1px solid #e5e7eb', borderRadius: '4px', cursor: 'pointer', fontSize: '1.1rem', background: groupForm.icon === emoji ? '#dbeafe' : '#fff' }}
                          className="hover:bg-gray-100">
                          {emoji}
                        </button>
                      ))}
                    </div>
                    <div style={{ marginTop: '6px', borderTop: '1px solid #e5e7eb', paddingTop: '6px' }}>
                      <label style={{ fontSize: '0.7rem', color: '#6b7280' }}>Or type a custom emoji:</label>
                      <input type="text" placeholder="Paste/type emoji" value={groupForm.icon}
                        onChange={e => setGroupForm(p => ({ ...p, icon: e.target.value }))}
                        className="px-2 py-1 border rounded text-sm mt-1" style={{ width: '100%' }} />
                    </div>
                  </div>
                )}
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                <label style={{ fontSize: '0.7rem', fontWeight: 600, color: '#374151' }}>Order</label>
                <input type="number" placeholder="#" value={groupForm.sort_order}
                  onChange={e => setGroupForm(p => ({ ...p, sort_order: Number(e.target.value) }))}
                  className="px-3 py-2 border rounded text-sm" style={{ width: '80px' }} />
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', justifyContent: 'flex-end' }}>
                <label style={{ fontSize: '0.7rem', color: 'transparent' }}>_</label>
                <label style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.85rem', cursor: 'pointer' }}>
                  <input type="checkbox" checked={groupForm.is_default}
                    onChange={e => setGroupForm(p => ({ ...p, is_default: e.target.checked }))} />
                  Default (auto-open)
                </label>
              </div>
            </div>

            {/* Row 2: Description */}
            <div className="mb-3">
              <label style={{ fontSize: '0.7rem', fontWeight: 600, color: '#374151' }}>Description</label>
              <input type="text" placeholder="Brief description of this navigation group (optional)" value={groupForm.description}
                onChange={e => setGroupForm(p => ({ ...p, description: e.target.value }))}
                className="px-3 py-2 border rounded text-sm w-full" />
            </div>

            {/* Row 3: Action buttons */}
            <div style={{ display: 'flex', gap: '8px' }}>
              {editingGroupId ? (
                <>
                  <button onClick={() => handleUpdateGroup(editingGroupId)}
                    className="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700 text-sm">💾 Save</button>
                  <button onClick={() => { setEditingGroupId(null); setGroupForm({ key: '', label: '', icon: '', description: '', sort_order: 0, is_default: false }); }}
                    className="px-4 py-2 bg-gray-400 text-white rounded hover:bg-gray-500 text-sm">Cancel</button>
                </>
              ) : (
                <button onClick={handleCreateGroup}
                  className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 text-sm">➕ Add Group</button>
              )}
            </div>
          </div>

          {/* ═══════════════════════════════════════════════════════════════ */}
          {/* SECTION 2: Navigation Groups & Their Items                     */}
          {/* ═══════════════════════════════════════════════════════════════ */}
          <h4 style={{ margin: '0 0 12px', fontSize: '1rem', fontWeight: 700, color: '#4338ca' }}>
            📋 Navigation Groups & Items
          </h4>
          <p style={{ margin: '0 0 16px', fontSize: '0.8rem', color: '#6b7280' }}>
            Each group represents a first-layer pill in the navigation bar. Items are the second-layer tabs shown when a group is expanded.
            Change the <strong>Order</strong> number to control display sequence within each group. Use the <strong>Move to</strong> dropdown to reassign items between groups.
          </p>

          {navGroups.map(group => {
            const groupItems = navItems.filter((i: any) => i.nav_group_id === group.id);
            return (
              <div key={group.id} style={{ marginBottom: '20px', border: '1px solid #e5e7eb', borderRadius: '8px', overflow: 'hidden' }}>
                {/* ── Group Header ── */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 14px',
                  background: group.is_default ? 'rgba(251,191,36,0.12)' : 'rgba(99,102,241,0.06)', justifyContent: 'space-between' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span style={{ fontSize: '1.1rem' }}>{group.icon}</span>
                    <strong>{group.label}</strong>
                    <span className="text-xs text-gray-500">({group.key})</span>
                    <span className="text-xs text-gray-400">order: {group.sort_order}</span>
                    {group.is_default && (
                      <span style={{ fontSize: '0.7rem', background: '#fbbf24', color: '#78350f', padding: '1px 8px', borderRadius: '10px', fontWeight: 700 }}>
                        ★ DEFAULT
                      </span>
                    )}
                  </div>
                  <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                    {!group.is_default && (
                      <button onClick={() => handleSetDefaultGroup(group.id)}
                        className="text-amber-600 hover:text-amber-800 text-sm" title="Set as default group (auto-opens on login)">★ Set Default</button>
                    )}
                    <button onClick={() => { setShowAddItem(showAddItem === group.id ? null : group.id); setItemForm(f => ({ ...f, nav_group_id: group.id })); }}
                      className="text-blue-600 hover:text-blue-800 text-sm" title="Add item to group">➕ Item</button>
                    <button onClick={() => startEditGroup(group)}
                      className="text-indigo-600 hover:text-indigo-800 text-sm" title="Edit group">✏️</button>
                    <button onClick={() => handleDeleteGroup(group.id)}
                      className="text-red-600 hover:text-red-800 text-sm" title="Delete group">🗑️</button>
                  </div>
                </div>

                {/* ── Add Item Form (collapsible) ── */}
                {showAddItem === group.id && !editingItemId && (
                  <div style={{ padding: '12px 14px', background: '#fffbeb', borderBottom: '1px solid #e5e7eb' }}>
                    <p style={{ margin: '0 0 8px', fontSize: '0.8rem', fontWeight: 600, color: '#92400e' }}>
                      ➕ Add New Item to "{group.label}"
                    </p>
                    <div className="flex gap-2" style={{ flexWrap: 'wrap', alignItems: 'center' }}>
                      <input type="text" placeholder="Key" value={itemForm.key}
                        onChange={e => setItemForm(p => ({ ...p, key: e.target.value }))}
                        className="px-2 py-1 border rounded text-sm" style={{ width: '100px' }} />
                      <input type="text" placeholder="Label" value={itemForm.label}
                        onChange={e => setItemForm(p => ({ ...p, label: e.target.value }))}
                        className="px-2 py-1 border rounded text-sm" style={{ width: '120px' }} />
                      <input type="text" placeholder="Icon" value={itemForm.icon}
                        onChange={e => setItemForm(p => ({ ...p, icon: e.target.value }))}
                        className="px-2 py-1 border rounded text-sm" style={{ width: '60px' }} />
                      <input type="text" placeholder="Route" value={itemForm.route}
                        onChange={e => setItemForm(p => ({ ...p, route: e.target.value }))}
                        className="px-2 py-1 border rounded text-sm" style={{ width: '100px' }} />
                      <input type="text" placeholder="Resource key" value={itemForm.resource_key}
                        onChange={e => setItemForm(p => ({ ...p, resource_key: e.target.value }))}
                        className="px-2 py-1 border rounded text-sm" style={{ width: '100px' }} />
                      <input type="number" placeholder="#" value={itemForm.sort_order}
                        onChange={e => setItemForm(p => ({ ...p, sort_order: Number(e.target.value) }))}
                        className="px-2 py-1 border rounded text-sm" style={{ width: '60px' }} />
                      <button onClick={handleCreateItem}
                        className="px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700 text-sm">Add</button>
                      <button onClick={() => setShowAddItem(null)}
                        className="px-3 py-1 bg-gray-400 text-white rounded hover:bg-gray-500 text-sm">Cancel</button>
                    </div>
                  </div>
                )}

                {/* ── Items Table ── */}
                <table className="w-full" style={{ fontSize: '0.85rem' }}>
                  <thead>
                    <tr style={{ background: '#f9fafb' }}>
                      <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Key</th>
                      <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Label</th>
                      <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Route</th>
                      <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Resource</th>
                      <th className="px-3 py-2 text-left text-xs font-medium text-gray-500" style={{ width: '70px' }}>Order #</th>
                      <th className="px-3 py-2 text-center text-xs font-medium text-gray-500" style={{ width: '55px' }} title="Active items are visible in navigation">Active</th>
                      <th className="px-3 py-2 text-center text-xs font-medium text-gray-500" style={{ width: '55px' }} title="Action items show with orange accent color">Action</th>
                      <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Move to</th>
                      <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {groupItems.map((item: any) => (
                      editingItemId === item.id ? (
                        <tr key={item.id} style={{ background: '#fffbeb' }}>
                          <td className="px-3 py-2"><input value={itemForm.key} disabled className="px-2 py-1 border rounded text-sm w-full bg-gray-100" /></td>
                          <td className="px-3 py-2">
                            <div className="flex gap-1">
                              <input value={itemForm.icon} onChange={e => setItemForm(p => ({...p, icon: e.target.value}))}
                                className="px-2 py-1 border rounded text-sm" style={{width:'40px'}} placeholder="🔹" />
                              <input value={itemForm.label} onChange={e => setItemForm(p => ({...p, label: e.target.value}))}
                                className="px-2 py-1 border rounded text-sm" style={{flex:1}} />
                            </div>
                          </td>
                          <td className="px-3 py-2"><input value={itemForm.route} onChange={e => setItemForm(p => ({...p, route: e.target.value}))}
                            className="px-2 py-1 border rounded text-sm w-full" /></td>
                          <td className="px-3 py-2"><input value={itemForm.resource_key} onChange={e => setItemForm(p => ({...p, resource_key: e.target.value}))}
                            className="px-2 py-1 border rounded text-sm w-full" /></td>
                          <td className="px-3 py-2"><input type="number" value={itemForm.sort_order} onChange={e => setItemForm(p => ({...p, sort_order: Number(e.target.value)}))}
                            className="px-2 py-1 border rounded text-sm" style={{width:'50px'}} /></td>
                          <td className="px-3 py-2 text-center">
                            <input type="checkbox" checked={itemForm.is_active} onChange={e => setItemForm(p => ({...p, is_active: e.target.checked}))}
                              title="Active — visible in navigation" />
                          </td>
                          <td className="px-3 py-2 text-center">
                            <input type="checkbox" checked={itemForm.is_action} onChange={e => setItemForm(p => ({...p, is_action: e.target.checked}))}
                              title="Action — shown with orange accent color" />
                          </td>
                          <td className="px-3 py-2">
                            <select value={itemForm.nav_group_id} onChange={e => setItemForm(p => ({...p, nav_group_id: Number(e.target.value)}))}
                              className="px-2 py-1 border rounded text-sm">
                              {navGroups.map((g: any) => <option key={g.id} value={g.id}>{g.label}</option>)}
                            </select>
                          </td>
                          <td className="px-3 py-2">
                            <div className="flex gap-1">
                              <button onClick={() => handleUpdateItem(item.id)} className="text-green-600 hover:text-green-800 text-sm">💾</button>
                              <button onClick={() => { setEditingItemId(null); setItemForm({ key:'', label:'', icon:'', route:'', resource_key:'', nav_group_id:0, sort_order:0, is_active: true, is_action: false }); }}
                                className="text-gray-500 hover:text-gray-700 text-sm">✖</button>
                            </div>
                          </td>
                        </tr>
                      ) : (
                        <tr key={item.id} className="hover:bg-gray-50">
                          <td className="px-3 py-2 text-sm">{item.key}</td>
                          <td className="px-3 py-2 text-sm">{item.icon} {item.label}</td>
                          <td className="px-3 py-2 text-sm text-gray-500">{item.route}</td>
                          <td className="px-3 py-2 text-sm text-gray-500">{item.resource_key || '—'}</td>
                          <td className="px-3 py-2 text-sm">
                            <input type="number" defaultValue={item.sort_order}
                              style={{ width: '50px', padding: '2px 4px', border: '1px solid #d1d5db', borderRadius: '4px', fontSize: '0.8rem', textAlign: 'center' }}
                              onBlur={(e) => {
                                const newVal = Number(e.target.value);
                                if (newVal !== item.sort_order) handleUpdateItemSortOrder(item.id, newVal);
                              }}
                              onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }}
                            />
                          </td>
                          <td className="px-3 py-2 text-center">
                            <span style={{ color: item.is_active !== false ? '#16a34a' : '#dc2626', fontWeight: 600 }}>{item.is_active !== false ? '✓' : '✗'}</span>
                          </td>
                          <td className="px-3 py-2 text-center">
                            <span style={{ color: item.is_action ? '#ea580c' : '#9ca3af' }}>{item.is_action ? '🔶' : '—'}</span>
                          </td>
                          <td className="px-3 py-2 text-sm">
                            <select value={item.nav_group_id}
                              onChange={e => handleMoveItem(item.id, Number(e.target.value))}
                              className="px-1 py-0.5 border rounded text-xs" style={{ maxWidth: '100px' }}>
                              {navGroups.map((g: any) => <option key={g.id} value={g.id}>{g.label}</option>)}
                            </select>
                          </td>
                          <td className="px-3 py-2 text-sm">
                            <div style={{ display: 'flex', gap: '4px' }}>
                              <button onClick={() => startEditItem(item)} className="text-indigo-600 hover:text-indigo-800">✏️</button>
                              <button onClick={() => handleDeleteItem(item.id)} className="text-red-600 hover:text-red-800">🗑️</button>
                            </div>
                          </td>
                        </tr>
                      )
                    ))}
                    {groupItems.length === 0 && (
                      <tr><td colSpan={9} className="px-3 py-4 text-center text-gray-400 text-sm">No items in this group</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            );
          })}
          {navGroups.length === 0 && (
            <p className="text-gray-500 text-center py-8">No navigation groups found. Run the migration first.</p>
          )}
        </div>
      )}

      {/* ── Department Visibility Tab ── */}
      {activeTab === 'visibility' && (
        <div className="bg-white rounded-lg border p-6">
          <h3 className="text-lg font-medium mb-4">👁️ Department Visibility</h3>
          <p className="text-sm text-gray-600 mb-4">
            Check or uncheck navigation groups and items for each department.
            Toggling a group toggles all items within it. Save per department.
          </p>
          {visMsg && (
            <div style={{ padding: '8px 12px', borderRadius: '6px', marginBottom: '12px',
              background: visMsg.startsWith('✅') ? '#dcfce7' : '#fee2e2',
              color: visMsg.startsWith('✅') ? '#166534' : '#991b1b', fontSize: '0.85rem' }}>
              {visMsg}
            </div>
          )}
          {departments.map(dept => {
            const deptVis = visEdits[dept.id] || { groups: new Set(), items: new Set() };
            return (
              <div key={dept.id} style={{ marginBottom: '24px', border: '1px solid #e5e7eb', borderRadius: '8px', padding: '16px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                  <h4 style={{ margin: 0, fontWeight: 600 }}>🏢 {dept.name}</h4>
                  <button onClick={() => handleSaveVisibility(dept.id)}
                    className="px-4 py-1 bg-blue-600 text-white rounded hover:bg-blue-700 text-sm">
                    💾 Save
                  </button>
                </div>
                {navGroups.map(group => {
                  const groupChecked = deptVis.groups.has(group.id);
                  const groupItems = navItems.filter(i => i.nav_group_id === group.id);
                  return (
                    <div key={group.id} style={{ marginBottom: '10px', marginLeft: '8px' }}>
                      <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 600, cursor: 'pointer', marginBottom: '4px' }}>
                        <input type="checkbox" checked={groupChecked}
                          onChange={() => toggleVisGroup(dept.id, group.id)} />
                        <span>{group.icon} {group.label}</span>
                      </label>
                      <div style={{ marginLeft: '28px', display: 'flex', flexWrap: 'wrap', gap: '4px 16px' }}>
                        {groupItems.map(item => (
                          <label key={item.id} style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.85rem', cursor: 'pointer' }}>
                            <input type="checkbox" checked={deptVis.items.has(item.id)}
                              onChange={() => toggleVisItem(dept.id, item.id)} />
                            {item.label}
                          </label>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            );
          })}
          {departments.length === 0 && (
            <p className="text-gray-500 text-center py-8">No departments found. Create departments first.</p>
          )}
        </div>
      )}

      {/* MFA Management Tab */}
      {activeTab === 'mfa' && (
        <div className="bg-white rounded-lg border">
          <div style={{ padding: '20px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <div>
                <h3 style={{ margin: 0, fontSize: '1.1rem', fontWeight: 600 }}>🔐 Multi-Factor Authentication</h3>
                <p style={{ margin: '4px 0 0', fontSize: '0.85rem', color: '#888' }}>
                  View and manage MFA enrollment for all users. Users can self-enroll via the 🔐 MFA button in the header.
                </p>
              </div>
              <button
                onClick={loadMfaUsers}
                disabled={mfaLoading}
                style={{ padding: '6px 14px', background: '#6366f1', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '0.85rem', fontWeight: 600 }}
              >
                {mfaLoading ? '⏳ Loading...' : '🔄 Refresh'}
              </button>
            </div>

            {mfaMsg && (
              <div style={{ padding: '10px', borderRadius: '6px', marginBottom: '12px', background: mfaMsg.startsWith('✅') ? '#dcfce7' : '#fee2e2', color: mfaMsg.startsWith('✅') ? '#166534' : '#991b1b', fontSize: '0.85rem' }}>
                {mfaMsg}
              </div>
            )}

            {/* Summary cards */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '12px', marginBottom: '20px' }}>
              <div style={{ padding: '14px', borderRadius: '10px', background: 'rgba(99,102,241,0.06)', border: '1px solid rgba(99,102,241,0.15)', textAlign: 'center' }}>
                <div style={{ fontSize: '1.8rem', fontWeight: 700, color: '#6366f1' }}>{mfaUsers.length}</div>
                <div style={{ fontSize: '0.8rem', color: '#888' }}>Total Users</div>
              </div>
              <div style={{ padding: '14px', borderRadius: '10px', background: 'rgba(34,197,94,0.06)', border: '1px solid rgba(34,197,94,0.15)', textAlign: 'center' }}>
                <div style={{ fontSize: '1.8rem', fontWeight: 700, color: '#22c55e' }}>{mfaUsers.filter(u => u.mfa_enabled).length}</div>
                <div style={{ fontSize: '0.8rem', color: '#888' }}>MFA Enabled</div>
              </div>
              <div style={{ padding: '14px', borderRadius: '10px', background: 'rgba(245,158,11,0.06)', border: '1px solid rgba(245,158,11,0.15)', textAlign: 'center' }}>
                <div style={{ fontSize: '1.8rem', fontWeight: 700, color: '#f59e0b' }}>{mfaUsers.filter(u => !u.mfa_enabled).length}</div>
                <div style={{ fontSize: '0.8rem', color: '#888' }}>Not Enrolled</div>
              </div>
            </div>

            {/* Users table */}
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-3 text-left text-sm font-medium text-gray-900">Username</th>
                    <th className="px-4 py-3 text-center text-sm font-medium text-gray-900">MFA Status</th>
                    <th className="px-4 py-3 text-left text-sm font-medium text-gray-900">Enrolled Date</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {mfaUsers.length === 0 && !mfaLoading ? (
                    <tr><td colSpan={3} className="px-4 py-8 text-center text-sm text-gray-500">No users found</td></tr>
                  ) : (
                    mfaUsers.map(u => (
                      <tr key={u.username} className="hover:bg-gray-50">
                        <td className="px-4 py-3 text-sm font-medium">{u.username}</td>
                        <td className="px-4 py-3 text-sm text-center">
                          {u.mfa_enabled ? (
                            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', padding: '2px 10px', borderRadius: '12px', background: '#dcfce7', color: '#166534', fontSize: '0.8rem', fontWeight: 600 }}>
                              ✅ Enabled
                            </span>
                          ) : (
                            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', padding: '2px 10px', borderRadius: '12px', background: '#f3f4f6', color: '#6b7280', fontSize: '0.8rem' }}>
                              — Not Enrolled
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-500">
                          {u.created_at ? new Date(u.created_at).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            {/* Info box */}
            <div style={{ marginTop: '20px', padding: '14px', borderRadius: '8px', background: 'rgba(99,102,241,0.05)', border: '1px solid rgba(99,102,241,0.12)', fontSize: '0.82rem', color: '#555' }}>
              <strong>ℹ️ How MFA Works:</strong>
              <ul style={{ margin: '8px 0 0', paddingLeft: '20px', lineHeight: '1.7' }}>
                <li>Users click the <strong>🔐 MFA</strong> button in the top header bar to enable MFA on their account</li>
                <li>They scan a QR code with <strong>Google Authenticator</strong> (or any TOTP app) and confirm with a 6-digit code</li>
                <li>Once enabled, login requires both LDAP password + TOTP code from the authenticator app</li>
                <li>8 one-time backup codes are provided during setup for account recovery</li>
              </ul>
            </div>
          </div>
        </div>
      )}

      {/* Branding Settings */}
      {activeTab === 'branding' && <BrandingSettings />}

      {/* Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-lg p-6 w-full max-w-md">
            <h3 className="text-lg font-medium mb-4">
              {editingItem ? 'Edit' : 'Add'} {modalType === 'user' ? 'User' : modalType}
            </h3>
            {modalType === 'user' && (
              <UserForm
                user={editingItem}
                onSave={(data) => {
                  if (editingItem) {
                    handleUpdateUserRole(data);
                  } else {
                    handleAddUser(data);
                  }
                }}
                onCancel={() => {
                  setShowModal(false);
                  setEditingItem(null);
                }}
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default UserManagement;