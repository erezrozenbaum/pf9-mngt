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
          { id: 3, name: 'operator', description: 'Operational access', userCount: users.filter(u => u.role === 'operator').length },
          { id: 4, name: 'viewer', description: 'Read-only access', userCount: users.filter(u => u.role === 'viewer').length }
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
          { id: 1, resource: 'servers', action: 'read', roles: ['viewer', 'operator', 'admin', 'superadmin'] },
          { id: 2, resource: 'servers', action: 'admin', roles: ['admin', 'superadmin'] },
          { id: 3, resource: 'volumes', action: 'read', roles: ['viewer', 'operator', 'admin', 'superadmin'] },
          { id: 4, resource: 'volumes', action: 'admin', roles: ['admin', 'superadmin'] },
          { id: 5, resource: 'snapshots', action: 'read', roles: ['viewer', 'operator', 'admin', 'superadmin'] },
          { id: 6, resource: 'snapshots', action: 'write', roles: ['admin', 'superadmin'] },
          { id: 7, resource: 'networks', action: 'read', roles: ['viewer', 'operator', 'admin', 'superadmin'] },
          { id: 8, resource: 'networks', action: 'write', roles: ['operator', 'admin', 'superadmin'] },
          { id: 9, resource: 'users', action: 'admin', roles: ['superadmin'] },
          { id: 10, resource: 'monitoring', action: 'read', roles: ['viewer', 'operator', 'admin', 'superadmin'] },
          { id: 11, resource: 'hypervisors', action: 'read', roles: ['viewer', 'operator', 'admin', 'superadmin'] },
          { id: 12, resource: 'flavors', action: 'write', roles: ['operator', 'admin', 'superadmin'] },
          { id: 13, resource: 'restore', action: 'read', roles: ['viewer', 'operator', 'admin', 'superadmin'] },
          { id: 14, resource: 'restore', action: 'write', roles: ['admin', 'superadmin'] },
          { id: 15, resource: 'restore', action: 'admin', roles: ['superadmin'] }
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

      if (response.ok) {
        await loadData();
        setShowModal(false);
        setEditingItem(null);
      } else {
        const errorData = await response.json();
        setError(errorData.detail || 'Failed to update user role');
      }
    } catch (err) {
      console.error('Error updating user role:', err);
      setError('Failed to update user role');
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
      status: user?.status || 'active'
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
          />
        </div>
        <div>
          <label className="block text-sm font-medium mb-1">Email</label>
          <input
            type="email"
            value={localFormData.email}
            onChange={(e) => setLocalFormData({...localFormData, email: e.target.value})}
            className="w-full p-2 border rounded"
            required
          />
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
    // All actual resources from the UI tabs
    // Only show permissions that actually exist in the data
    // Sort permissions by resource, then by action
    const sortedPermissions = [...permissions].sort((a, b) => {
      if (a.resource !== b.resource) return a.resource.localeCompare(b.resource);
      return a.action.localeCompare(b.action);
    });
    
    return (
      <div className="overflow-x-auto">
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
            content: '✓';
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
        <table className="w-full border-collapse border border-gray-700">
          <thead>
            <tr>
              <th className="border border-gray-700 p-2 bg-gray-800">Resource</th>
              <th className="border border-gray-700 p-2 bg-gray-800">Action</th>
              {roles.map(role => (
                <th key={role.id} className="border border-gray-700 p-2 bg-gray-800 text-center">{role.name}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sortedPermissions.map((permission, idx) => (
              <tr key={`${permission.resource}-${permission.action}-${idx}`}>
                <td className="border border-gray-700 p-2">{permission.resource}</td>
                <td className="border border-gray-700 p-2">{permission.action}</td>
                {roles.map(role => (
                  <td key={role.id} className="border border-gray-700 p-2 text-center">
                    <input
                      type="checkbox"
                      checked={permission.roles.includes(role.name)}
                      onChange={(e) => {
                        // Handle permission change
                        console.log(`Toggle ${permission.resource}:${permission.action} for ${role.name}`);
                      }}
                      className="permission-checkbox"
                      disabled={true}  // Read-only for now
                    />
                  </td>
                ))}
              </tr>
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
          <span>Loading CCC authentication users...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold">CCC Authentication Management</h1>
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
      <div className="flex border-b mb-6">
        {[
          { id: 'users', label: 'LDAP Users', icon: '👥', adminOnly: true },
          { id: 'roles', label: 'Roles', icon: '🛡️', adminOnly: true },
          { id: 'permissions', label: 'Permissions', icon: '🔑', adminOnly: true },
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
          <h3 className="text-lg font-medium mb-4">Permission Matrix</h3>
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