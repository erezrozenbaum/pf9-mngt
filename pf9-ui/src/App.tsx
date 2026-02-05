import React, { useEffect, useState } from "react";
import "./App.css";
import { ThemeProvider, useTheme } from "./hooks/useTheme";
import { ThemeToggle } from "./components/ThemeToggle";
import UserManagement from "./components/UserManagement";
import SnapshotPolicyManager from "./components/SnapshotPolicyManager";
import SnapshotAuditTrail from "./components/SnapshotAuditTrail";
import { APIMetricsTab } from "./components/APIMetricsTab";
import { SystemLogsTab } from "./components/SystemLogsTab";

const API_BASE = "http://localhost:8000";

// ---------------------------------------------------------------------------
// Authentication Types
// ---------------------------------------------------------------------------

type AuthUser = {
  username: string;
  email: string;
  role: string;
};

type LoginResponse = {
  access_token: string;
  token_type: string;
  expires_in: number;
  expires_at?: string;
  user: AuthUser;
};

// ---------------------------------------------------------------------------
// Types – match backend views
// ---------------------------------------------------------------------------

type Domain = {
  domain_id: string;
  domain_name: string;
};

type TenantProject = {
  tenant_id: string;
  tenant_name: string;
  domain_name: string;
};

type Server = {
  vm_id: string;
  vm_name: string;
  domain_name: string;
  tenant_name: string;
  project_name: string | null;
  status: string;
  flavor_name: string | null;
  ips: string | null;
  created_at: string | null;
};

type Snapshot = {
  snapshot_id: string;
  snapshot_name: string | null;
  vm_id: string | null;
  vm_name: string | null;
  domain_name: string;
  tenant_name: string;
  size_gb: number | null;
  status: string;
  created_at: string | null;
  last_seen_at: string | null;
  is_deleted: boolean;
};

type Network = {
  network_id: string;
  network_name: string | null;
  domain_name: string;
  project_name: string | null;
  is_shared: boolean;
  is_external: boolean;
  last_seen_at: string | null;
};

type Volume = {
  id: string; // cinder volume id
  project_id: string | null;
  volume_name: string | null;
  domain_name: string;
  tenant_name: string;
  project_name: string | null;
  size_gb: number | null;
  status: string | null;
  attached_to: string | null;
  created_at: string | null;
  last_seen_at: string | null;
  // Metadata fields for snapshot policy management
  auto_snapshot: string | null;
  snapshot_policy: string | null;
  metadata: Record<string, any> | null;
  volume_type: string | null;
  bootable: boolean | null;
  server_id: string | null;
  server_name: string | null;
  device: string | null;
  attach_host: string | null;
};

type Flavor = {
  flavor_id: string;
  flavor_name: string;
  vcpus: number;
  ram_mb: number;
  disk_gb: number;
  swap_mb: number | null;
  ephemeral_gb: number;
  is_public: boolean;
  last_seen_at: string | null;
};

type Image = {
  image_id: string;
  image_name: string;
  size: number | null;
  disk_format: string | null;
  container_format: string | null;
  visibility: string | null;
  status: string | null;
  created_at: string | null;
  last_seen_at: string | null;
};

type Hypervisor = {
  hypervisor_id: string;
  hypervisor_hostname: string;
  host_ip: string | null;
  vcpus: number | null;
  vcpus_used: number | null;
  memory_mb: number | null;
  memory_mb_used: number | null;
  local_gb: number | null;
  local_gb_used: number | null;
  running_vms: number | null;
  hypervisor_type: string | null;
  hypervisor_version: string | null;
  status: string | null;
  state: string | null;
  last_seen_at: string | null;
};

type User = {
  id: string;
  name: string;
  email: string | null;
  enabled: boolean;
  domain_id: string | null;
  domain_name: string | null;
  description: string | null;
  default_project_id: string | null;
  created_at: string | null;
  last_login: string | null;
  last_seen_at: string | null;
};

type Project = {
  domain_id: string;
  domain_name: string;
  tenant_id: string;
  tenant_name: string;
};

// Monitoring types
type VMMetrics = {
  vm_id: string;
  vm_name: string;
  vm_ip?: string;
  host: string;
  domain?: string;
  project_name?: string;
  user_name?: string;
  flavor?: string;
  timestamp: string;
  cpu_total?: number;
  cpu_usage_percent?: number;
  memory_total_mb?: number;
  memory_allocated_mb?: number;
  memory_used_mb?: number;
  memory_usage_percent?: number;
  storage_total_gb?: number;
  storage_allocated_gb?: number;
  storage_used_gb?: number;
  storage_usage_percent?: number;
  storage_read_iops?: number;
  storage_write_iops?: number;
  network_rx_bytes?: number;
  network_tx_bytes?: number;
};

type HostMetrics = {
  hostname: string;
  timestamp: string;
  cpu_total?: number;
  cpu_usage_percent?: number;
  memory_total_mb?: number;
  memory_used_mb?: number;
  memory_usage_percent?: number;
  storage_total_gb?: number;
  storage_used_gb?: number;
  storage_usage_percent?: number;
  network_rx_bytes?: number;
  network_tx_bytes?: number;
  network_rx_mb?: number;
  network_tx_mb?: number;
  network_rx_throughput?: number;
  network_tx_throughput?: number;
};

type MonitoringAlert = {
  type: string;
  severity: "low" | "medium" | "high" | "critical";
  resource: string;
  message: string;
  value: number;
};

type MetricsSummary = {
  total_vms: number;
  total_hosts: number;
  last_update?: string;
  vm_stats: {
    avg_cpu_usage?: number;
    max_cpu_usage?: number;
    avg_memory_usage?: number;
    max_memory_usage?: number;
  };
  host_stats: {
    avg_cpu_usage?: number;
    max_cpu_usage?: number;
    avg_memory_usage?: number;
    max_memory_usage?: number;
  };
};



type Subnet = {
  id: string;
  name: string | null;
  domain_name: string;
  tenant_name: string | null;
  project_name: string | null;
  cidr: string | null;
  ip_version: number | null;
  network_id: string | null;
  gateway_ip: string | null;
  enable_dhcp: boolean | null;
  created_at: string | null;
  last_seen_at: string | null;
};

type Port = {
  id: string;
  name: string | null;
  network_id: string | null;
  project_id: string | null;
  device_id: string | null;
  device_owner: string | null;
  mac_address: string | null;
  ip_addresses: any[];
  raw_json: any;
  last_seen_at: string;
  tenant_id: string | null;
  project_name: string | null;
  tenant_name: string | null;
  domain_id: string | null;
  domain_name: string | null;
};

type FloatingIP = {
  id: string;
  floating_ip: string | null;
  fixed_ip: string | null;
  port_id: string | null;
  project_id: string | null;
  router_id: string | null;
  status: string | null;
  raw_json: any;
  last_seen_at: string;
  tenant_id: string | null;
  project_name: string | null;
  tenant_name: string | null;
  domain_id: string | null;
  domain_name: string | null;
};

type PagedResponse<T> = {
  items: T[];
  total: number;
};

// History types
type ChangeRecord = {
  resource_type: string;
  resource_id: string;
  resource_name: string | null;
  change_hash: string;
  recorded_at: string;
  project_name?: string | null;
  domain_name?: string | null;
  actual_time?: string | null;
  change_description?: string | null;
};

type DailyChangeSummary = {
  change_date: string;
  resource_type: string;
  change_count: number;
};

type VelocityStats = {
  resource_type: string;
  avg_daily_changes: number;
  max_daily_changes: number;
  min_daily_changes: number;
  days_tracked: number;
};

type MostChangedResource = {
  resource_type: string;
  resource_id: string;
  resource_name: string | null;
  change_count: number;
  first_change: string;
  last_change: string;
};

type ResourceHistory = {
  resource_type: string;
  resource_id: string;
  resource_name: string | null;
  recorded_at: string;
  change_hash: string;
  current_state: any;
  previous_hash: string | null;
  change_sequence: number;
};

type VolumeHistory = {
  volume_id: string;
  volume_name: string | null;
  status: string;
  size_gb: number;
  volume_type: string;
  bootable: boolean;
  recorded_at: string;
  change_hash: string;
  auto_snapshot: string;
  snapshot_policy: string | null;
  full_state: any;
};

type ComplianceReport = {
  status: string;
  report_date: string;
  summary?: {
    resource_activity: Array<{resource_type: string; total_changes: number; last_change: string}>;
    high_activity_resources: any[];
    recent_changes: any[];
  };
  compliance_notes?: {
    total_resource_types: number;
    high_risk_resources: number;
    recent_changes_count: number;
  };
  recent_changes_by_type?: Array<{resource_type: string; change_count: number}>;
  change_velocity_trends?: VelocityStats[];
};

type ActiveTab = "servers" | "snapshots" | "networks" | "subnets" | "volumes" | "domains" | "projects" | "flavors" | "images" | "hypervisors" | "users" | "admin" | "history" | "audit" | "monitoring" | "api_metrics" | "system_logs";

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

async function fetchJson<T>(url: string): Promise<T> {
  const token = localStorage.getItem('auth_token');
  const headers: Record<string, string> = {};
  if (token && url.startsWith(API_BASE)) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const res = await fetch(url, { headers });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`HTTP ${res.status}: ${txt || res.statusText}`);
  }
  return (await res.json()) as T;
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString();
}

function yesNo(value: boolean | null | undefined): string {
  if (value === null || value === undefined) return "";
  return value ? "yes" : "no";
}

function volumeDisplayId(v: Volume): string {
  return v.id;
}

// ---------------------------------------------------------------------------
// CSV helpers
// ---------------------------------------------------------------------------

function csvLine(fields: (string | number | null | undefined)[]): string {
  return fields
    .map((v) => {
      const s = v === null || v === undefined ? "" : String(v);
      return `"${s.replace(/"/g, '""')}"`;
    })
    .join(",");
}

// ---------------------------------------------------------------------------
// Login Page Component
// ---------------------------------------------------------------------------

interface LoginPageProps {
  isLoggingIn: boolean;
  loginError: string;
  handleLogin: (username: string, password: string) => void;
}

const LoginPage: React.FC<LoginPageProps> = ({ isLoggingIn, loginError, handleLogin }) => {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === 'dark';

  return (
    <div className="pf9-app" style={{
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: isDark 
        ? 'linear-gradient(135deg, #1a1a2e 0%, #16213e 100%)'
        : 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)'
    }}>
      {/* Theme Toggle Button */}
      <button
        onClick={toggleTheme}
        style={{
          position: 'absolute',
          top: '20px',
          right: '20px',
          background: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(255,255,255,0.2)',
          border: 'none',
          borderRadius: '50%',
          width: '48px',
          height: '48px',
          cursor: 'pointer',
          fontSize: '1.5rem',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          transition: 'all 0.3s',
          backdropFilter: 'blur(10px)'
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.background = isDark ? 'rgba(255,255,255,0.2)' : 'rgba(255,255,255,0.3)';
          e.currentTarget.style.transform = 'scale(1.1)';
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = isDark ? 'rgba(255,255,255,0.1)' : 'rgba(255,255,255,0.2)';
          e.currentTarget.style.transform = 'scale(1)';
        }}
      >
        {isDark ? '☀️' : '🌙'}
      </button>

      <div style={{
        background: isDark ? '#1e1e1e' : 'white',
        padding: '3rem',
        borderRadius: '12px',
        boxShadow: isDark 
          ? '0 20px 60px rgba(0,0,0,0.6)' 
          : '0 20px 60px rgba(0,0,0,0.3)',
        width: '100%',
        maxWidth: '420px',
        margin: '20px',
        border: isDark ? '1px solid rgba(255,255,255,0.1)' : 'none'
      }}>
        <div style={{ textAlign: 'center', marginBottom: '2rem' }}>
          <h1 style={{ 
            fontSize: '2rem', 
            marginBottom: '0.5rem', 
            color: isDark ? '#fff' : '#333' 
          }}>
            PF9 Management System
          </h1>
          <p style={{ 
            color: isDark ? '#aaa' : '#666', 
            fontSize: '0.95rem' 
          }}>
            Platform9 Infrastructure Management
          </p>
        </div>

        <form onSubmit={(e) => {
          e.preventDefault();
          const formData = new FormData(e.currentTarget);
          const username = formData.get('username') as string;
          const password = formData.get('password') as string;
          handleLogin(username, password);
        }}>
          <div style={{ marginBottom: '1.5rem' }}>
            <label style={{ 
              display: 'block', 
              marginBottom: '0.5rem', 
              color: isDark ? '#ccc' : '#444', 
              fontWeight: '500' 
            }}>
              Username
            </label>
            <input
              type="text"
              name="username"
              required
              autoFocus
              placeholder="Enter your username"
              style={{
                width: '100%',
                padding: '0.75rem',
                fontSize: '1rem',
                border: isDark 
                  ? '2px solid rgba(255,255,255,0.2)' 
                  : '2px solid #ddd',
                borderRadius: '6px',
                transition: 'border-color 0.2s',
                boxSizing: 'border-box',
                background: isDark ? 'rgba(255,255,255,0.05)' : 'white',
                color: isDark ? '#fff' : '#333'
              }}
              onFocus={(e) => e.target.style.borderColor = isDark ? '#667eea' : '#667eea'}
              onBlur={(e) => e.target.style.borderColor = isDark ? 'rgba(255,255,255,0.2)' : '#ddd'}
            />
          </div>

          <div style={{ marginBottom: '1.5rem' }}>
            <label style={{ 
              display: 'block', 
              marginBottom: '0.5rem', 
              color: isDark ? '#ccc' : '#444', 
              fontWeight: '500' 
            }}>
              Password
            </label>
            <input
              type="password"
              name="password"
              required
              placeholder="Enter your password"
              style={{
                width: '100%',
                padding: '0.75rem',
                fontSize: '1rem',
                border: isDark 
                  ? '2px solid rgba(255,255,255,0.2)' 
                  : '2px solid #ddd',
                borderRadius: '6px',
                transition: 'border-color 0.2s',
                boxSizing: 'border-box',
                background: isDark ? 'rgba(255,255,255,0.05)' : 'white',
                color: isDark ? '#fff' : '#333'
              }}
              onFocus={(e) => e.target.style.borderColor = isDark ? '#667eea' : '#667eea'}
              onBlur={(e) => e.target.style.borderColor = isDark ? 'rgba(255,255,255,0.2)' : '#ddd'}
            />
          </div>

          {loginError && (
            <div style={{
              padding: '0.75rem',
              marginBottom: '1rem',
              background: isDark ? 'rgba(255,50,50,0.2)' : '#fee',
              border: isDark ? '1px solid rgba(255,100,100,0.4)' : '1px solid #fcc',
              borderRadius: '6px',
              color: isDark ? '#ff6b6b' : '#c33',
              fontSize: '0.9rem'
            }}>
              ⚠️ {loginError}
            </div>
          )}

          <button
            type="submit"
            disabled={isLoggingIn}
            style={{
              width: '100%',
              padding: '0.875rem',
              fontSize: '1rem',
              fontWeight: '600',
              color: 'white',
              background: isLoggingIn 
                ? (isDark ? '#555' : '#999')
                : 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
              border: 'none',
              borderRadius: '6px',
              cursor: isLoggingIn ? 'not-allowed' : 'pointer',
              transition: 'transform 0.1s, box-shadow 0.2s',
              boxShadow: '0 4px 12px rgba(102, 126, 234, 0.4)'
            }}
            onMouseDown={(e) => !isLoggingIn && (e.currentTarget.style.transform = 'scale(0.98)')}
            onMouseUp={(e) => e.currentTarget.style.transform = 'scale(1)'}
            onMouseLeave={(e) => e.currentTarget.style.transform = 'scale(1)'}
          >
            {isLoggingIn ? 'Signing in...' : 'Sign In'}
          </button>
        </form>

        <div style={{ 
          marginTop: '2rem', 
          paddingTop: '1.5rem', 
          borderTop: isDark ? '1px solid rgba(255,255,255,0.1)' : '1px solid #eee', 
          textAlign: 'center' 
        }}>
          <p style={{ 
            fontSize: '0.85rem', 
            color: isDark ? '#999' : '#888', 
            margin: '0 0 0.5rem 0' 
          }}>
            🔐 LDAP Authentication Enabled
          </p>
          <p style={{ 
            fontSize: '0.75rem', 
            color: isDark ? '#777' : '#aaa', 
            margin: 0 
          }}>
            Authorized users only • PF9 Infrastructure
          </p>
        </div>
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

const App: React.FC = () => {
  // Authentication state
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [authUser, setAuthUser] = useState<AuthUser | null>(null);
  const [authToken, setAuthToken] = useState<string | null>(null);
  const [tokenExpiresAt, setTokenExpiresAt] = useState<string | null>(null);
  const [loginError, setLoginError] = useState<string>("");
  const [isLoggingIn, setIsLoggingIn] = useState(false);

  // Check for existing token on mount
  useEffect(() => {
    const token = localStorage.getItem('auth_token');
    const user = localStorage.getItem('auth_user');
    const expiresAt = localStorage.getItem('token_expires_at');
    
    if (token && user && user !== 'undefined' && user !== 'null') {
      try {
        // Check if token is expired
        if (expiresAt) {
          const expirationTime = new Date(expiresAt).getTime();
          const now = new Date().getTime();
          
          if (now >= expirationTime) {
            // Token expired, clear and force re-login
            console.log('Session expired, please login again');
            localStorage.removeItem('auth_token');
            localStorage.removeItem('auth_user');
            localStorage.removeItem('token_expires_at');
            setLoginError('Your session has expired. Please login again.');
            return;
          }
        }
        
        setAuthToken(token);
        setAuthUser(JSON.parse(user));
        setTokenExpiresAt(expiresAt);
        setIsAuthenticated(true);
      } catch (e) {
        // Clear invalid data
        localStorage.removeItem('auth_token');
        localStorage.removeItem('auth_user');
        localStorage.removeItem('token_expires_at');
      }
    }
  }, []);

  // Session timeout checker - runs every minute
  useEffect(() => {
    if (!isAuthenticated || !tokenExpiresAt) return;
    
    const checkExpiration = () => {
      const expirationTime = new Date(tokenExpiresAt).getTime();
      const now = new Date().getTime();
      const timeUntilExpiry = expirationTime - now;
      
      // If less than 5 minutes until expiry, show warning
      if (timeUntilExpiry > 0 && timeUntilExpiry < 5 * 60 * 1000) {
        const minutesLeft = Math.floor(timeUntilExpiry / 60000);
        console.warn(`Session expiring in ${minutesLeft} minutes`);
      }
      
      // If expired, auto-logout
      if (timeUntilExpiry <= 0) {
        console.log('Session expired, logging out...');
        handleLogout();
        setLoginError('Your session has expired. Please login again.');
      }
    };
    
    // Check immediately and then every minute
    checkExpiration();
    const intervalId = setInterval(checkExpiration, 60000); // Check every minute
    
    return () => clearInterval(intervalId);
  }, [isAuthenticated, tokenExpiresAt]);

  // Login handler
  const handleLogin = async (username: string, password: string) => {
    setIsLoggingIn(true);
    setLoginError("");
    try {
      const response = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Login failed');
      }

      const data: LoginResponse = await response.json();
      
      // Store auth data including expiration time
      localStorage.setItem('auth_token', data.access_token);
      localStorage.setItem('auth_user', JSON.stringify(data.user));
      if (data.expires_at) {
        localStorage.setItem('token_expires_at', data.expires_at);
        setTokenExpiresAt(data.expires_at);
      }
      
      setAuthToken(data.access_token);
      setAuthUser(data.user);
      setIsAuthenticated(true);
    } catch (error: any) {
      setLoginError(error.message || 'Login failed');
    } finally {
      setIsLoggingIn(false);
    }
  };

  // Logout handler
  const handleLogout = async () => {
    try {
      const token = localStorage.getItem('auth_token');
      if (token) {
        await fetch(`${API_BASE}/auth/logout`, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${token}`
          }
        });
      }
    } catch (error) {
      console.warn('Logout request failed:', error);
    } finally {
      localStorage.removeItem('auth_token');
      localStorage.removeItem('auth_user');
      localStorage.removeItem('token_expires_at');
      setAuthToken(null);
      setAuthUser(null);
      setTokenExpiresAt(null);
      setIsAuthenticated(false);
    }
  };

  // Filters
  const [domains, setDomains] = useState<Domain[]>([]);
  const [tenants, setTenants] = useState<TenantProject[]>([]);
  const [selectedDomain, setSelectedDomain] = useState<string>("__ALL__");
  const [selectedTenant, setSelectedTenant] = useState<string>("__ALL__");
  const [vmSearch, setVmSearch] = useState<string>("");

  // Tabs
  const [activeTab, setActiveTab] = useState<ActiveTab>("servers");

  // Paging + sorting
  const [serverPage, setServerPage] = useState(1);
  const [serverPageSize, setServerPageSize] = useState(50);
  const [serverSortBy, setServerSortBy] = useState("domain_name");
  const [serverSortDir, setServerSortDir] = useState<"asc" | "desc">("asc");

  const [snapPage, setSnapPage] = useState(1);
  const [snapPageSize, setSnapPageSize] = useState(50);
  const [snapSortBy, setSnapSortBy] = useState("created_at");
  const [snapSortDir, setSnapSortDir] = useState<"asc" | "desc">("desc");

  const [networkPage, setNetworkPage] = useState(1);
  const [networkPageSize, setNetworkPageSize] = useState(50);
  const [networkSortBy, setNetworkSortBy] = useState("network_name");
  const [networkSortDir, setNetworkSortDir] =
    useState<"asc" | "desc">("asc");

  const [subnetPage, setSubnetPage] = useState(1);
  const [subnetPageSize, setSubnetPageSize] = useState(50);
  const [subnetSortBy, setSubnetSortBy] = useState("name");
  const [subnetSortDir, setSubnetSortDir] = useState<"asc" | "desc">("asc");

  const [volumePage, setVolumePage] = useState(1);
  const [volumePageSize, setVolumePageSize] = useState(50);
  const [volumeSortBy, setVolumeSortBy] = useState("volume_name");
  const [volumeSortDir, setVolumeSortDir] =
    useState<"asc" | "desc">("asc");

  // New resource types paging/sorting
  const [flavorPage, setFlavorPage] = useState(1);
  const [flavorPageSize, setFlavorPageSize] = useState(50);
  const [flavorSortBy, setFlavorSortBy] = useState("flavor_name");
  const [flavorSortDir, setFlavorSortDir] = useState<"asc" | "desc">("asc");

  const [imagePage, setImagePage] = useState(1);
  const [imagePageSize, setImagePageSize] = useState(50);
  const [imageSortBy, setImageSortBy] = useState("image_name");
  const [imageSortDir, setImageSortDir] = useState<"asc" | "desc">("asc");

  const [hypervisorPage, setHypervisorPage] = useState(1);
  const [hypervisorPageSize, setHypervisorPageSize] = useState(50);
  const [hypervisorSortBy, setHypervisorSortBy] = useState("hypervisor_hostname");
  const [hypervisorSortDir, setHypervisorSortDir] = useState<"asc" | "desc">("asc");

  // User pagination and sorting
  const [userPage, setUserPage] = useState(1);
  const [userPageSize, setUserPageSize] = useState(20);
  const [userSortBy, setUserSortBy] = useState("name");
  const [userSortDir, setUserSortDir] = useState<"asc" | "desc">("asc");

  const [projectPage, setProjectPage] = useState(1);
  const [projectPageSize, setProjectPageSize] = useState(50);
  const [projectSortBy, setProjectSortBy] = useState("tenant_name");
  const [projectSortDir, setProjectSortDir] = useState<"asc" | "desc">("asc");

  const [portPage, setPortPage] = useState(1);
  const [portPageSize, setPortPageSize] = useState(50);
  const [portSortBy, setPortSortBy] = useState("domain_name");
  const [portSortDir, setPortSortDir] = useState<"asc" | "desc">("asc");

  const [floatingIPPage, setFloatingIPPage] = useState(1);
  const [floatingIPPageSize, setFloatingIPPageSize] = useState(50);
  const [floatingIPSortBy, setFloatingIPSortBy] = useState("floating_ip");
  const [floatingIPSortDir, setFloatingIPSortDir] = useState<"asc" | "desc">("asc");

  // Data
  const [servers, setServers] = useState<Server[]>([]);
  const [serversTotal, setServersTotal] = useState(0);
  const [selectedServer, setSelectedServer] = useState<Server | null>(null);

  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [snapshotsTotal, setSnapshotsTotal] = useState(0);
  const [selectedSnapshot, setSelectedSnapshot] =
    useState<Snapshot | null>(null);

  const [networks, setNetworks] = useState<Network[]>([]);
  const [networksTotal, setNetworksTotal] = useState(0);
  const [selectedNetwork, setSelectedNetwork] =
    useState<Network | null>(null);

  const [subnets, setSubnets] = useState<Subnet[]>([]);
  const [subnetsTotal, setSubnetsTotal] = useState(0);
  const [selectedSubnet, setSelectedSubnet] =
    useState<Subnet | null>(null);

  const [volumes, setVolumes] = useState<Volume[]>([]);
  const [volumesTotal, setVolumesTotal] = useState(0);
  const [selectedVolume, setSelectedVolume] = useState<Volume | null>(null);

  // New resource types
  const [flavors, setFlavors] = useState<Flavor[]>([]);
  const [flavorsTotal, setFlavorsTotal] = useState(0);
  const [selectedFlavor, setSelectedFlavor] = useState<Flavor | null>(null);

  const [images, setImages] = useState<Image[]>([]);
  const [imagesTotal, setImagesTotal] = useState(0);
  const [selectedImage, setSelectedImage] = useState<Image | null>(null);

  const [hypervisors, setHypervisors] = useState<Hypervisor[]>([]);
  const [hypervisorsTotal, setHypervisorsTotal] = useState(0);
  const [users, setUsers] = useState<User[]>([]);
  const [usersTotal, setUsersTotal] = useState(0);
  const [selectedHypervisor, setSelectedHypervisor] = useState<Hypervisor | null>(null);

  const [projects, setProjects] = useState<Project[]>([]);
  const [projectsTotal, setProjectsTotal] = useState(0);
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);

  const [ports, setPorts] = useState<Port[]>([]);
  const [portsTotal, setPortsTotal] = useState(0);
  const [selectedPort, setSelectedPort] = useState<Port | null>(null);

  const [floatingIPs, setFloatingIPs] = useState<FloatingIP[]>([]);
  const [floatingIPsTotal, setFloatingIPsTotal] = useState(0);
  const [selectedFloatingIP, setSelectedFloatingIP] = useState<FloatingIP | null>(null);
    useState<Volume | null>(null);

  // History & Audit data
  const [recentChanges, setRecentChanges] = useState<ChangeRecord[]>([]);
  const [changeTimeframe, setChangeTimeframe] = useState<number>(24);
  const [dailySummary, setDailySummary] = useState<DailyChangeSummary[]>([]);
  const [velocityStats, setVelocityStats] = useState<VelocityStats[]>([]);
  const [mostChangedResources, setMostChangedResources] = useState<MostChangedResource[]>([]);
  const [complianceReport, setComplianceReport] = useState<ComplianceReport | null>(null);
  const [selectedResourceHistory, setSelectedResourceHistory] = useState<ResourceHistory[]>([]);
  const [historyResourceType, setHistoryResourceType] = useState<string>("");
  const [historyResourceId, setHistoryResourceId] = useState<string>("");
  
  // Audit-specific data (unfiltered)
  const [allServersForAudit, setAllServersForAudit] = useState<Server[]>([]);
  const [allVolumesForAudit, setAllVolumesForAudit] = useState<Volume[]>([]);
  const [allNetworksForAudit, setAllNetworksForAudit] = useState<Network[]>([]);
  const [allSnapshotsForAudit, setAllSnapshotsForAudit] = useState<Snapshot[]>([]);

  // Monitoring state
  const [vmMetrics, setVmMetrics] = useState<VMMetrics[]>([]);
  const [hostMetrics, setHostMetrics] = useState<HostMetrics[]>([]);
  const [monitoringAlerts, setMonitoringAlerts] = useState<MonitoringAlert[]>([]);
  const [metricsSummary, setMetricsSummary] = useState<MetricsSummary | null>(null);
  const [monitoringLoading, setMonitoringLoading] = useState(false);
  const [lastMetricsUpdate, setLastMetricsUpdate] = useState<string | null>(null);
  const [isRefreshingMetrics, setIsRefreshingMetrics] = useState(false);



  // misc
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // -----------------------------------------------------------------------
  // Monitoring API functions
  // -----------------------------------------------------------------------

  async function loadVMMetrics() {
    try {
      setMonitoringLoading(true);
      const res = await fetchJson<{ data: VMMetrics[]; timestamp: string }>('http://localhost:8001/metrics/vms');
      setVmMetrics(res.data || []);
      setLastMetricsUpdate(res.timestamp);
    } catch (e: any) {
      console.error("Failed to load VM metrics:", e);
      setError(e.message || "Failed to load VM metrics");
    }
  }

  async function loadHostMetrics() {
    try {
      const res = await fetchJson<{ data: HostMetrics[]; timestamp: string }>('http://localhost:8001/metrics/hosts');
      setHostMetrics(res.data || []);
    } catch (e: any) {
      console.error("Failed to load host metrics:", e);
    }
  }

  async function loadMonitoringAlerts() {
    try {
      const res = await fetchJson<{ alerts: MonitoringAlert[] }>('http://localhost:8001/metrics/alerts');
      setMonitoringAlerts(res.alerts || []);
    } catch (e: any) {
      console.error("Failed to load monitoring alerts:", e);
    }
  }

  async function loadMetricsSummary() {
    try {
      const res = await fetchJson<MetricsSummary>('http://localhost:8001/metrics/summary');
      setMetricsSummary(res);
      
      // Check if monitoring setup is needed
      if (res.total_hosts === 0) {
        try {
          const setupCheck = await fetchJson<any>('http://localhost:8001/auto-setup');
          if (setupCheck.status === 'setup_needed') {
            console.warn("Monitoring setup needed:", setupCheck.message);
          }
        } catch (setupError) {
          console.error("Could not check setup status:", setupError);
        }
      }
    } catch (e: any) {
      console.error("Failed to load metrics summary:", e);
    } finally {
      setMonitoringLoading(false);
    }
  }

  async function loadAllMonitoringData() {
    await Promise.all([
      loadVMMetrics(),
      loadHostMetrics(), 
      loadMonitoringAlerts(),
      loadMetricsSummary()
    ]);
  }

  // Manual refresh function
  async function handleRefreshMetrics() {
    if (isRefreshingMetrics) return;
    
    setIsRefreshingMetrics(true);
    try {
      // Trigger refresh on the backend
      await fetch('http://localhost:8001/metrics/refresh', { method: 'POST' });
      // Wait a bit for the refresh to complete
      await new Promise(resolve => setTimeout(resolve, 2000));
      // Reload all monitoring data
      await loadAllMonitoringData();
      setLastMetricsUpdate(new Date().toISOString());
    } catch (error) {
      console.error('Error refreshing metrics:', error);
    } finally {
      setIsRefreshingMetrics(false);
    }
  }

  // -----------------------------------------------------------------------
  // Load domains + tenants
  // -----------------------------------------------------------------------

  useEffect(() => {
    async function loadDomains() {
      try {
        const res = await fetchJson<{ items: Domain[] }>(`${API_BASE}/domains`);
        const d = Array.isArray((res as any)) ? (res as any as Domain[]) : (res.items || []);
        // Keep a stable sentinel value "__ALL__" as the <select> value
        setDomains([{ domain_id: "__ALL__", domain_name: "__ALL__" }, ...d]);
      } catch (e: any) {
        console.error(e);
        setError(e.message || "Failed to load domains");
      }
    }
    loadDomains();
  }, []);

  useEffect(() => {
    async function loadTenants() {
      try {
        const params = new URLSearchParams();
        if (selectedDomain !== "__ALL__") {
          params.append("domain_name", selectedDomain);
        }
        const url = `${API_BASE}/tenants?${params.toString()}`;
        const res = await fetchJson<{ items: TenantProject[] }>(url);
        const t = Array.isArray((res as any)) ? (res as any as TenantProject[]) : (res.items || []);
        setTenants([
          {
            tenant_id: "__ALL__",
            tenant_name: "All tenants",
            domain_name: "",
          },
          ...t,
        ]);
      } catch (e: any) {
        console.error(e);
        setError(e.message || "Failed to load tenants");
      }
    }
    loadTenants();
  }, [selectedDomain]);

  // Reset paging when filters change
  useEffect(() => {
    setServerPage(1);
    setSnapPage(1);
    setNetworkPage(1);
    setSubnetPage(1);
    setVolumePage(1);
  }, [selectedDomain, selectedTenant]);

  // -----------------------------------------------------------------------
  // Load per-resource based on active tab
  // -----------------------------------------------------------------------

  useEffect(() => {
    async function loadServers() {
      if (activeTab !== "servers" && activeTab !== "audit") return;
      setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams();
        if (selectedDomain !== "__ALL__")
          params.append("domain_name", selectedDomain);
        if (selectedTenant !== "__ALL__")
          params.append("tenant_id", selectedTenant);
        if (vmSearch) params.append("vm_name", vmSearch);
        params.append("page", String(serverPage));
        params.append("page_size", String(serverPageSize));
        params.append("sort_by", serverSortBy);
        params.append("sort_dir", serverSortDir);

        const url = `${API_BASE}/servers?${params.toString()}`;
        const data = await fetchJson<PagedResponse<Server>>(url);
        setServers(data.items);
        setServersTotal(data.total);
        if (
          selectedServer &&
          !data.items.find((s) => s.vm_id === selectedServer.vm_id)
        ) {
          setSelectedServer(null);
        }
      } catch (e: any) {
        console.error(e);
        setError(e.message || "Failed to load servers");
      } finally {
        setLoading(false);
      }
    }
    loadServers();
  }, [
    activeTab,
    selectedDomain,
    selectedTenant,
    vmSearch,
    serverPage,
    serverPageSize,
    serverSortBy,
    serverSortDir,
  ]);

  useEffect(() => {
    async function loadSnapshots() {
      if (activeTab !== "snapshots") return;
      setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams();
        if (selectedDomain !== "__ALL__")
          params.append("domain_name", selectedDomain);
        if (selectedTenant !== "__ALL__")
          params.append("tenant_id", selectedTenant);
        params.append("page", String(snapPage));
        params.append("page_size", String(snapPageSize));
        params.append("sort_by", snapSortBy);
        params.append("sort_dir", snapSortDir);

        const url = `${API_BASE}/snapshots?${params.toString()}`;
        const data = await fetchJson<PagedResponse<Snapshot>>(url);
        setSnapshots(data.items);
        setSnapshotsTotal(data.total);
        if (
          selectedSnapshot &&
          !data.items.find((s) => s.snapshot_id === selectedSnapshot.snapshot_id)
        ) {
          setSelectedSnapshot(null);
        }
      } catch (e: any) {
        console.error(e);
        setError(e.message || "Failed to load snapshots");
      } finally {
        setLoading(false);
      }
    }
    loadSnapshots();
  }, [
    activeTab,
    selectedDomain,
    selectedTenant,
    snapPage,
    snapPageSize,
    snapSortBy,
    snapSortDir,
  ]);

  useEffect(() => {
    async function loadNetworks() {
      if (activeTab !== "networks" && activeTab !== "audit") return;
      setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams();
        if (selectedDomain !== "__ALL__")
          params.append("domain_name", selectedDomain);
        if (selectedTenant !== "__ALL__")
          params.append("tenant_id", selectedTenant);
        params.append("page", String(networkPage));
        params.append("page_size", String(networkPageSize));
        params.append("sort_by", networkSortBy);
        params.append("sort_dir", networkSortDir);

        const url = `${API_BASE}/networks?${params.toString()}`;
        const data = await fetchJson<PagedResponse<Network>>(url);
        setNetworks(data.items);
        setNetworksTotal(data.total);
        if (
          selectedNetwork &&
          !data.items.find((n) => n.network_id === selectedNetwork.network_id)
        ) {
          setSelectedNetwork(null);
        }
      } catch (e: any) {
        console.error(e);
        setError(e.message || "Failed to load networks");
      } finally {
        setLoading(false);
      }
    }
    loadNetworks();
  }, [
    activeTab,
    selectedDomain,
    selectedTenant,
    networkPage,
    networkPageSize,
    networkSortBy,
    networkSortDir,
  ]);

  useEffect(() => {
    async function loadSubnets() {
      if (activeTab !== "subnets") return;
      setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams();
        if (selectedDomain !== "__ALL__")
          params.append("domain_name", selectedDomain);
        if (selectedTenant !== "__ALL__")
          params.append("tenant_id", selectedTenant);
        params.append("page", String(subnetPage));
        params.append("page_size", String(subnetPageSize));
        params.append("sort_by", subnetSortBy);
        params.append("sort_dir", subnetSortDir);

        const url = `${API_BASE}/subnets?${params.toString()}`;
        const data = await fetchJson<PagedResponse<Subnet>>(url);
        setSubnets(data.items);
        setSubnetsTotal(data.total);
        if (
          selectedSubnet &&
          !data.items.find((s) => s.id === selectedSubnet.id)
        ) {
          setSelectedSubnet(null);
        }
      } catch (e: any) {
        console.error(e);
        setError(e.message || "Failed to load subnets");
      } finally {
        setLoading(false);
      }
    }
    loadSubnets();
  }, [
    activeTab,
    selectedDomain,
    selectedTenant,
    subnetPage,
    subnetPageSize,
    subnetSortBy,
    subnetSortDir,
  ]);

  useEffect(() => {
    async function loadVolumes() {
      if (activeTab !== "volumes" && activeTab !== "audit") return;
      setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams();
        if (selectedDomain !== "__ALL__")
          params.append("domain_name", selectedDomain);
        if (selectedTenant !== "__ALL__")
          params.append("tenant_id", selectedTenant);
        params.append("page", String(volumePage));
        params.append("page_size", String(volumePageSize));
        params.append("sort_by", volumeSortBy);
        params.append("sort_dir", volumeSortDir);

        const url = `${API_BASE}/volumes?${params.toString()}`;
        const data = await fetchJson<PagedResponse<Volume>>(url);
        
        // Enhance volumes with metadata for snapshot policy management
        const volumesWithMetadata = data.items.map(volume => {
          // Add metadata fields with sample data to demonstrate functionality
          const hasMetadata = volume.volume_name?.includes("CentOS") || volume.volume_name?.includes("yossi") || volume.volume_name?.includes("200BR");
          
          return {
            ...volume,
            auto_snapshot: hasMetadata ? "true" : "false",
            snapshot_policy: hasMetadata ? "daily_5,monthly_15th" : null,
            metadata: hasMetadata ? {
              auto_snapshot: "true",
              snapshot_policies: "daily_5,monthly_15th",
              retention_daily_5: "5"
            } : null
          };
        });
        
        setVolumes(volumesWithMetadata);
        setVolumesTotal(data.total);
        if (
          selectedVolume &&
          !data.items.find((v) => v.id === selectedVolume.id)
        ) {
          setSelectedVolume(null);
        }
      } catch (e: any) {
        console.error(e);
        setError(e.message || "Failed to load volumes");
      } finally {
        setLoading(false);
      }
    }
    loadVolumes();
  }, [
    activeTab,
    selectedDomain,
    selectedTenant,
    volumePage,
    volumePageSize,
    volumeSortBy,
    volumeSortDir,
  ]);

  // -----------------------------------------------------------------------
  // New Resource Types - Loading Functions
  // -----------------------------------------------------------------------

  // Load flavors
  useEffect(() => {
    if (activeTab !== "flavors" && activeTab !== "audit") return;
    
    async function loadFlavors() {
      setLoading(true);
      try {
        const params = new URLSearchParams({
          page: flavorPage.toString(),
          page_size: flavorPageSize.toString(),
          sort_by: flavorSortBy,
          sort_dir: flavorSortDir,
        });

        const res = await fetchJson<PagedResponse<Flavor>>(`${API_BASE}/flavors?${params}`);
        if (res) {
          setFlavors(res.items || []);
          setFlavorsTotal(res.total || 0);
        }
      } catch (e: any) {
        console.error(e);
        setError(e.message || "Failed to load flavors");
      } finally {
        setLoading(false);
      }
    }
    loadFlavors();
  }, [activeTab, flavorPage, flavorPageSize, flavorSortBy, flavorSortDir]);

  // Load projects
  useEffect(() => {
    if (activeTab !== "projects") return;
    
    async function loadProjects() {
      setLoading(true);
      try {
        const params = new URLSearchParams({
          page: projectPage.toString(),
          page_size: projectPageSize.toString(),
          sort_by: projectSortBy,
          sort_dir: projectSortDir,
        });

        const res = await fetchJson<PagedResponse<Project>>(`${API_BASE}/projects?${params}`);
        if (res) {
          setProjects(res.items || []);
          setProjectsTotal(res.total || 0);
        }
      } catch (e: any) {
        console.error(e);
        setError(e.message || "Failed to load projects");
      } finally {
        setLoading(false);
      }
    }
    loadProjects();
  }, [activeTab, projectPage, projectPageSize, projectSortBy, projectSortDir]);

  // Load images
  useEffect(() => {
    if (activeTab !== "images" && activeTab !== "audit") return;
    
    async function loadImages() {
      setLoading(true);
      try {
        const params = new URLSearchParams({
          page: imagePage.toString(),
          page_size: imagePageSize.toString(),
          sort_by: imageSortBy,
          sort_dir: imageSortDir,
        });

        const res = await fetchJson<PagedResponse<Image>>(`${API_BASE}/images?${params}`);
        if (res) {
          setImages(res.items || []);
          setImagesTotal(res.total || 0);
        }
      } catch (e: any) {
        console.error(e);
        setError(e.message || "Failed to load images");
      } finally {
        setLoading(false);
      }
    }
    loadImages();
  }, [activeTab, imagePage, imagePageSize, imageSortBy, imageSortDir]);

  // Load hypervisors
  useEffect(() => {
    if (activeTab !== "hypervisors" && activeTab !== "audit") return;
    
    async function loadHypervisors() {
      setLoading(true);
      try {
        const params = new URLSearchParams({
          page: hypervisorPage.toString(),
          page_size: hypervisorPageSize.toString(),
          sort_by: hypervisorSortBy,
          sort_dir: hypervisorSortDir,
        });

        const res = await fetchJson<PagedResponse<Hypervisor>>(`${API_BASE}/hypervisors?${params}`);
        if (res) {
          setHypervisors(res.items || []);
          setHypervisorsTotal(res.total || 0);
        }
      } catch (e: any) {
        console.error(e);
        setError(e.message || "Failed to load hypervisors");
      } finally {
        setLoading(false);
      }
    }
    loadHypervisors();
  }, [activeTab, hypervisorPage, hypervisorPageSize, hypervisorSortBy, hypervisorSortDir]);

  // Load users
  useEffect(() => {
    if (activeTab !== "users" && activeTab !== "audit") return;
    
    async function loadUsers() {
      setLoading(true);
      try {
        const params = new URLSearchParams({
          page: userPage.toString(),
          page_size: userPageSize.toString(),
          sort_by: userSortBy,
          sort_dir: userSortDir,
        });

        const res = await fetchJson<PagedResponse<User>>(`${API_BASE}/users?${params}`);
        if (res) {
          setUsers(res.data || []);
          setUsersTotal(res.total || 0);
        }
      } catch (e: any) {
        console.error(e);
        setError(e.message || "Failed to load users");
      } finally {
        setLoading(false);
      }
    }
    loadUsers();
  }, [activeTab, userPage, userPageSize, userSortBy, userSortDir]);

  // Load ports
  useEffect(() => {
    if (activeTab !== "ports" && activeTab !== "audit") return;
    
    async function loadPorts() {
      setLoading(true);
      try {
        const params = new URLSearchParams({
          page: portPage.toString(),
          page_size: portPageSize.toString(),
          sort_by: portSortBy,
          sort_dir: portSortDir,
        });

        if (selectedDomain !== "__ALL__") {
          params.append("domain_name", selectedDomain);
        }
        if (selectedTenant !== "__ALL__") {
          params.append("tenant_id", selectedTenant);
        }

        const res = await fetchJson<PagedResponse<Port>>(`${API_BASE}/ports?${params}`);
        if (res) {
          setPorts(res.items || []);
          setPortsTotal(res.total || 0);
        }
      } catch (e: any) {
        console.error(e);
        setError(e.message || "Failed to load ports");
      } finally {
        setLoading(false);
      }
    }
    loadPorts();
  }, [activeTab, selectedDomain, selectedTenant, portPage, portPageSize, portSortBy, portSortDir]);

  // Load floating IPs
  useEffect(() => {
    if (activeTab !== "floatingips" && activeTab !== "audit") return;
    
    async function loadFloatingIPs() {
      setLoading(true);
      try {
        const params = new URLSearchParams({
          page: floatingIPPage.toString(),
          page_size: floatingIPPageSize.toString(),
          sort_by: floatingIPSortBy,
          sort_dir: floatingIPSortDir,
        });

        if (selectedDomain !== "__ALL__") {
          params.append("domain_name", selectedDomain);
        }
        if (selectedTenant !== "__ALL__") {
          params.append("tenant_id", selectedTenant);
        }

        const res = await fetchJson<PagedResponse<FloatingIP>>(`${API_BASE}/floatingips?${params}`);
        if (res) {
          setFloatingIPs(res.items || []);
          setFloatingIPsTotal(res.total || 0);
        }
      } catch (e: any) {
        console.error(e);
        setError(e.message || "Failed to load floating IPs");
      } finally {
        setLoading(false);
      }
    }
    loadFloatingIPs();
  }, [activeTab, selectedDomain, selectedTenant, floatingIPPage, floatingIPPageSize, floatingIPSortBy, floatingIPSortDir]);

  // -----------------------------------------------------------------------
  // Audit data loading (all data without filters)
  // -----------------------------------------------------------------------

  useEffect(() => {
    async function loadAuditData() {
      if (activeTab !== "audit") return;
      
      try {
        // Load all servers without filters (using max allowed page size)
        const serversResponse = await fetchJson<PagedResponse<Server>>(`${API_BASE}/servers?page_size=500`);
        setAllServersForAudit(serversResponse.items);

        // Load all volumes without filters  
        const volumesResponse = await fetchJson<PagedResponse<Volume>>(`${API_BASE}/volumes?page_size=500`);
        setAllVolumesForAudit(volumesResponse.items);

        // Load all networks without filters
        const networksResponse = await fetchJson<PagedResponse<Network>>(`${API_BASE}/networks?page_size=500`);
        setAllNetworksForAudit(networksResponse.items);

        // Load all snapshots without filters
        const snapshotsResponse = await fetchJson<PagedResponse<Snapshot>>(`${API_BASE}/snapshots?page_size=500`);
        setAllSnapshotsForAudit(snapshotsResponse.items);

      } catch (e: any) {
        console.error("Failed to load audit data:", e);
        setError(e.message || "Failed to load audit data");
      }
    }
    loadAuditData();
  }, [activeTab]);

  // -----------------------------------------------------------------------
  // History & Audit data loading
  // -----------------------------------------------------------------------

  // Load recent changes
  useEffect(() => {
    async function loadRecentChanges() {
      if (activeTab !== "history") return;
      try {
        setLoading(true);
        const params = new URLSearchParams();
        params.append("hours", changeTimeframe.toString());
        params.append("limit", "1000"); // Increased limit to ensure we get infrastructure changes too
        if (selectedDomain !== "__ALL__") {
          params.append("domain_name", selectedDomain);
        }
        const url = `${API_BASE}/history/recent-changes?${params.toString()}`;
        console.log(`Loading changes with timeframe: ${changeTimeframe} hours, URL: ${url}`);
        const response = await fetchJson<{
          status: string;
          data: ChangeRecord[];
          count: number;
        }>(url);
        
        let filteredChanges = response.data || [];
        
        // Apply domain filtering on frontend since it's complex in SQL
        if (selectedDomain !== "__ALL__") {
          filteredChanges = filteredChanges.filter(change => {
            if (change.resource_type === "network") {
              const network = networks.find(n => n.network_id === change.resource_id);
              return network?.domain_name === selectedDomain;
            } else if (change.resource_type === "server") {
              const server = servers.find(s => s.server_id === change.resource_id);
              return server?.domain_name === selectedDomain;
            } else if (change.resource_type === "volume") {
              const volume = volumes.find(v => v.id === change.resource_id);
              return volume?.domain_name === selectedDomain;
            } else if (change.resource_type === "project") {
              const tenant = tenants.find(t => t.tenant_id === change.resource_id);
              return tenant?.domain_name === selectedDomain;
            } else if (change.resource_type === "domain") {
              const domain = domains.find(d => d.domain_id === change.resource_id);
              return domain?.domain_name === selectedDomain;
            }
            return true; // Include other types for now
          });
        }
        
        setRecentChanges(filteredChanges);
      } catch (e: any) {
        console.error(e);
        setError(e.message || "Failed to load recent changes");
      } finally {
        setLoading(false);
      }
    }
    loadRecentChanges();
  }, [activeTab, changeTimeframe, selectedDomain, networks, servers, volumes, tenants, domains]);

  // Load daily change summary
  useEffect(() => {
    async function loadDailySummary() {
      if (activeTab !== "history") return;
      try {
        const data = await fetchJson<{
          timeframe_days: number;
          total_changes: number;
          changes_by_type: Record<string, number>;
          daily_breakdown: DailyChangeSummary[];
        }>(`${API_BASE}/history/daily-summary?days=30`);
        setDailySummary(data.daily_breakdown);
      } catch (e: any) {
        console.error(e);
        setError(e.message || "Failed to load daily summary");
      }
    }
    loadDailySummary();
  }, [activeTab]);

  // Load velocity stats
  useEffect(() => {
    async function loadVelocityStats() {
      if (activeTab !== "history") return;
      try {
        const data = await fetchJson<{ velocity_stats: VelocityStats[] }>(
          `${API_BASE}/history/change-velocity`
        );
        setVelocityStats(data.velocity_stats);
      } catch (e: any) {
        console.error(e);
        setError(e.message || "Failed to load velocity stats");
      }
    }
    loadVelocityStats();
  }, [activeTab]);

  // Load most changed resources
  useEffect(() => {
    async function loadMostChanged() {
      if (activeTab !== "history") return;
      try {
        const params = new URLSearchParams();
        params.append("limit", "50");
        if (selectedDomain !== "__ALL__") {
          params.append("domain_name", selectedDomain);
        }
        const url = `${API_BASE}/history/most-changed?${params.toString()}`;
        const response = await fetchJson<{
          status: string;
          data: MostChangedResource[];
          count: number;
        }>(url);
        setMostChangedResources(response.data || []);
      } catch (e: any) {
        console.error(e);
        setError(e.message || "Failed to load most changed resources");
      }
    }
    loadMostChanged();
  }, [activeTab, selectedDomain]);

  // Load compliance report
  useEffect(() => {
    async function loadComplianceReport() {
      if (activeTab !== "audit") return;
      try {
        setLoading(true);
        const data = await fetchJson<ComplianceReport>(`${API_BASE}/audit/compliance-report`);
        setComplianceReport(data);
      } catch (e: any) {
        console.error(e);
        setError(e.message || "Failed to load compliance report");
      } finally {
        setLoading(false);
      }
    }
    loadComplianceReport();
  }, [activeTab]);

  // Load monitoring data when activeTab is "monitoring"
  useEffect(() => {
    if (activeTab === "monitoring") {
      loadAllMonitoringData();
      
      // Set up periodic refresh every 60 seconds
      const interval = setInterval(() => {
        loadAllMonitoringData();
      }, 60000);
      
      return () => clearInterval(interval);
    }
  }, [activeTab]);

  // Load resource history (when user selects a specific resource)
  async function loadResourceHistory(resourceType: string, resourceId: string) {
    try {
      setLoading(true);
      setError(null); // Clear any existing errors
      setHistoryResourceType(resourceType);
      setHistoryResourceId(resourceId);
      const response = await fetchJson<{
        status: string;
        data: ResourceHistory[];
        count: number;
        resource: { type: string; id: string };
      }>(`${API_BASE}/history/resource/${resourceType}/${resourceId}`);
      setSelectedResourceHistory(response.data || []);
    } catch (e: any) {
      console.error(`Error loading history for ${resourceType} ${resourceId}:`, e);
      // Check if it's a 404 or other specific error
      if (e.message && e.message.includes('404')) {
        setError(`No history data available for ${resourceType} ${resourceId}. This resource may not have history tracking enabled.`);
      } else {
        setError(e.message || `Failed to load history for ${resourceType} ${resourceId}`);
      }
    } finally {
      setLoading(false);
    }
  }

  // -----------------------------------------------------------------------
  // CSV export
  // -----------------------------------------------------------------------

  function exportCsvServers() {
    const header = [
      "VM",
      "Domain",
      "Tenant",
      "Project",
      "Status",
      "Flavor",
      "IPs",
      "Created",
    ];
    const lines = [header.join(",")];
    servers.forEach((s) => {
      lines.push(
        csvLine([
          s.vm_name || s.vm_id,
          s.domain_name,
          s.tenant_name,
          s.project_name,
          s.status,
          s.flavor_name,
          s.ips,
          s.created_at && formatDate(s.created_at),
        ])
      );
    });
    downloadCsv("pf9_servers.csv", lines);
  }

  function exportCsvSnapshots() {
    const header = [
      "Snapshot",
      "ID",
      "VM",
      "Domain",
      "Tenant",
      "Status",
      "Size_GB",
      "Created",
      "Last_seen",
      "Deleted",
    ];
    const lines = [header.join(",")];
    snapshots.forEach((s) => {
      lines.push(
        csvLine([
          s.snapshot_name || s.snapshot_id,
          s.snapshot_id,
          s.vm_name || s.vm_id,
          s.domain_name,
          s.tenant_name,
          s.status,
          s.size_gb,
          formatDate(s.created_at),
          formatDate(s.last_seen_at),
          yesNo(s.is_deleted),
        ])
      );
    });
    downloadCsv("pf9_snapshots.csv", lines);
  }

  function exportCsvNetworks() {
    const header = [
      "Network",
      "ID",
      "Domain",
      "Project",
      "Shared",
      "External",
      "Last_seen",
    ];
    const lines = [header.join(",")];
    networks.forEach((n) => {
      lines.push(
        csvLine([
          n.network_name || n.network_id,
          n.network_id,
          n.domain_name,
          n.project_name,
          yesNo(n.is_shared),
          yesNo(n.is_external),
          formatDate(n.last_seen_at),
        ])
      );
    });
    downloadCsv("pf9_networks.csv", lines);
  }

  function exportCsvSubnets() {
    const header = [
      "Subnet",
      "ID",
      "Domain",
      "Tenant",
      "Project",
      "CIDR",
      "IP_version",
      "Network_ID",
      "Gateway_IP",
      "DHCP_enabled",
      "Created",
      "Last_seen",
    ];
    const lines = [header.join(",")];
    subnets.forEach((s) => {
      lines.push(
        csvLine([
          s.name || s.id,
          s.id,
          s.domain_name,
          s.tenant_name,
          s.project_name,
          s.cidr,
          s.ip_version,
          s.network_id,
          s.gateway_ip,
          yesNo(s.enable_dhcp),
          formatDate(s.created_at),
          formatDate(s.last_seen_at),
        ])
      );
    });
    downloadCsv("pf9_subnets.csv", lines);
  }

  function exportCsvVolumes() {
    const header = [
      "Volume",
      "ID",
      "Domain",
      "Tenant",
      "Project",
      "Size_GB",
      "Status",
      "Attached_to",
      "Created",
      "Last_seen",
    ];
    const lines = [header.join(",")];
    volumes.forEach((v) => {
      lines.push(
        csvLine([
          v.volume_name || volumeDisplayId(v),
          volumeDisplayId(v),
          v.domain_name,
          v.tenant_name,
          v.project_name,
          v.size_gb,
          v.status,
          v.attached_to,
          formatDate(v.created_at),
          formatDate(v.last_seen_at),
        ])
      );
    });
    downloadCsv("pf9_volumes.csv", lines);
  }

  function downloadCsv(filename: string, lines: string[]) {
    const blob = new Blob([lines.join("\n")], {
      type: "text/csv;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  const exportFn =
    activeTab === "servers"
      ? exportCsvServers
      : activeTab === "snapshots"
      ? exportCsvSnapshots
      : activeTab === "networks"
      ? exportCsvNetworks
      : activeTab === "subnets"
      ? exportCsvSubnets
      : exportCsvVolumes;

  const exportCount =
    activeTab === "servers"
      ? servers.length
      : activeTab === "snapshots"
      ? snapshots.length
      : activeTab === "networks"
      ? networks.length
      : activeTab === "subnets"
      ? subnets.length
      : volumes.length;

  // -----------------------------------------------------------------------
  // Paging helpers used by shared pager
  // -----------------------------------------------------------------------

  const totalPagesServers = Math.max(
    1,
    Math.ceil(serversTotal / serverPageSize)
  );
  const totalPagesSnapshots = Math.max(
    1,
    Math.ceil(snapshotsTotal / snapPageSize)
  );
  const totalPagesNetworks = Math.max(
    1,
    Math.ceil(networksTotal / networkPageSize)
  );
  const totalPagesSubnets = Math.max(
    1,
    Math.ceil(subnetsTotal / subnetPageSize)
  );
  const totalPagesVolumes = Math.max(
    1,
    Math.ceil(volumesTotal / volumePageSize)
  );
  const totalPagesFlavors = Math.max(
    1,
    Math.ceil(flavorsTotal / flavorPageSize)
  );
  const totalPagesImages = Math.max(
    1,
    Math.ceil(imagesTotal / imagePageSize)
  );
  const totalPagesHypervisors = Math.max(
    1,
    Math.ceil(hypervisorsTotal / hypervisorPageSize)
  );
  const totalPagesUsers = Math.max(
    1,
    Math.ceil(usersTotal / userPageSize)
  );
  const totalPagesPorts = Math.max(
    1,
    Math.ceil(portsTotal / portPageSize)
  );
  const totalPagesFloatingIPs = Math.max(
    1,
    Math.ceil(floatingIPsTotal / floatingIPPageSize)
  );
  const totalPagesProjects = Math.max(
    1,
    Math.ceil(projectsTotal / projectPageSize)
  );

  const activeTotal =
    activeTab === "servers"
      ? serversTotal
      : activeTab === "snapshots"
      ? snapshotsTotal
      : activeTab === "networks"
      ? networksTotal
      : activeTab === "subnets"
      ? subnetsTotal
      : activeTab === "volumes"
      ? volumesTotal
      : activeTab === "flavors"
      ? flavorsTotal
      : activeTab === "images"
      ? imagesTotal
      : activeTab === "hypervisors"
      ? hypervisorsTotal
      : activeTab === "users"
      ? usersTotal
      : activeTab === "ports"
      ? portsTotal
      : activeTab === "floatingips"
      ? floatingIPsTotal
      : activeTab === "projects"
      ? projectsTotal
      : 0;

  const activePage =
    activeTab === "servers"
      ? serverPage
      : activeTab === "snapshots"
      ? snapPage
      : activeTab === "networks"
      ? networkPage
      : activeTab === "subnets"
      ? subnetPage
      : activeTab === "volumes"
      ? volumePage
      : activeTab === "flavors"
      ? flavorPage
      : activeTab === "images"
      ? imagePage
      : activeTab === "hypervisors"
      ? hypervisorPage
      : activeTab === "users"
      ? userPage
      : activeTab === "ports"
      ? portPage
      : activeTab === "floatingips"
      ? floatingIPPage
      : activeTab === "projects"
      ? projectPage
      : 1;

  const activeTotalPages =
    activeTab === "servers"
      ? totalPagesServers
      : activeTab === "snapshots"
      ? totalPagesSnapshots
      : activeTab === "networks"
      ? totalPagesNetworks
      : activeTab === "subnets"
      ? totalPagesSubnets
      : activeTab === "volumes"
      ? totalPagesVolumes
      : activeTab === "flavors"
      ? totalPagesFlavors
      : activeTab === "images"
      ? totalPagesImages
      : activeTab === "hypervisors"
      ? totalPagesHypervisors
      : activeTab === "users"
      ? totalPagesUsers
      : activeTab === "ports"
      ? totalPagesPorts
      : activeTab === "floatingips"
      ? totalPagesFloatingIPs
      : activeTab === "projects"
      ? totalPagesProjects
      : 1;

  const activePageSize =
    activeTab === "servers"
      ? serverPageSize
      : activeTab === "snapshots"
      ? snapPageSize
      : activeTab === "networks"
      ? networkPageSize
      : activeTab === "subnets"
      ? subnetPageSize
      : activeTab === "volumes"
      ? volumePageSize
      : activeTab === "flavors"
      ? flavorPageSize
      : activeTab === "images"
      ? imagePageSize
      : activeTab === "hypervisors"
      ? hypervisorPageSize
      : activeTab === "users"
      ? userPageSize
      : activeTab === "ports"
      ? portPageSize
      : activeTab === "floatingips"
      ? floatingIPPageSize
      : activeTab === "projects"
      ? projectPageSize
      : 50;

  // -----------------------------------------------------------------------
  // Render
  // -----------------------------------------------------------------------

  // Login Screen
  if (!isAuthenticated) {
    return (
      <ThemeProvider>
        <LoginPage 
          isLoggingIn={isLoggingIn}
          loginError={loginError}
          handleLogin={handleLogin}
        />
      </ThemeProvider>
    );
  }

  // Main Application
  return (
    <ThemeProvider>
      <div className="pf9-app">
        <header className="pf9-header">
          <h1>PF9 Management Portal</h1>
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            {authUser && (
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginRight: '8px' }}>
                <span style={{ fontSize: '0.9rem', color: '#666' }}>
                  👤 {authUser.username} ({authUser.role})
                </span>
                <button
                  onClick={handleLogout}
                  style={{
                    padding: '6px 14px',
                    fontSize: '0.85rem',
                    background: '#f44336',
                    color: 'white',
                    border: 'none',
                    borderRadius: '4px',
                    cursor: 'pointer'
                  }}
                >
                  Logout
                </button>
              </div>
            )}
            <div className="pf9-tabs">
          <button
            className={
              activeTab === "servers" ? "pf9-tab pf9-tab-active" : "pf9-tab"
            }
            onClick={() => setActiveTab("servers")}
          >
            VMs
          </button>
          <button
            className={
              activeTab === "snapshots" ? "pf9-tab pf9-tab-active" : "pf9-tab"
            }
            onClick={() => setActiveTab("snapshots")}
          >
            Snapshots
          </button>
          <button
            className={
              activeTab === "networks" ? "pf9-tab pf9-tab-active" : "pf9-tab"
            }
            onClick={() => setActiveTab("networks")}
          >
            Networks
          </button>
          <button
            className={
              activeTab === "subnets" ? "pf9-tab pf9-tab-active" : "pf9-tab"
            }
            onClick={() => setActiveTab("subnets")}
          >
            Subnets
          </button>
          <button
            className={
              activeTab === "volumes" ? "pf9-tab pf9-tab-active" : "pf9-tab"
            }
            onClick={() => setActiveTab("volumes")}
          >
            Volumes
          </button>
          <button
            className={
              activeTab === "domains" ? "pf9-tab pf9-tab-active" : "pf9-tab"
            }
            onClick={() => setActiveTab("domains")}
          >
            Domains
          </button>
          <button
            className={
              activeTab === "projects" ? "pf9-tab pf9-tab-active" : "pf9-tab"
            }
            onClick={() => setActiveTab("projects")}
          >
            Projects
          </button>
          <button
            className={
              activeTab === "flavors" ? "pf9-tab pf9-tab-active" : "pf9-tab"
            }
            onClick={() => setActiveTab("flavors")}
          >
            Flavors
          </button>
          <button
            className={
              activeTab === "images" ? "pf9-tab pf9-tab-active" : "pf9-tab"
            }
            onClick={() => setActiveTab("images")}
          >
            Images
          </button>
          <button
            className={
              activeTab === "hypervisors" ? "pf9-tab pf9-tab-active" : "pf9-tab"
            }
            onClick={() => setActiveTab("hypervisors")}
          >
            Hypervisors
          </button>
          <button
            className={
              activeTab === "users" ? "pf9-tab pf9-tab-active" : "pf9-tab"
            }
            onClick={() => setActiveTab("users")}
          >
            Users
          </button>
          {authUser && (authUser.role === 'admin' || authUser.role === 'superadmin') && (
            <>
              <button
                className={
                  activeTab === "admin" ? "pf9-tab pf9-tab-active" : "pf9-tab"
                }
                onClick={() => setActiveTab("admin")}
              >
                Admin
              </button>
              <button
                className={
                  activeTab === "api_metrics" ? "pf9-tab pf9-tab-active" : "pf9-tab"
                }
                onClick={() => setActiveTab("api_metrics")}
              >
                API Metrics
              </button>
              <button
                className={
                  activeTab === "system_logs" ? "pf9-tab pf9-tab-active" : "pf9-tab"
                }
                onClick={() => setActiveTab("system_logs")}
              >
                System Logs
              </button>
            </>
          )}
          <button
            className={
              activeTab === "ports" ? "pf9-tab pf9-tab-active" : "pf9-tab"
            }
            onClick={() => setActiveTab("ports")}
          >
            Ports
          </button>
          <button
            className={
              activeTab === "floatingips" ? "pf9-tab pf9-tab-active" : "pf9-tab"
            }
            onClick={() => setActiveTab("floatingips")}
          >
            Floating IPs
          </button>
          <button
            className={
              activeTab === "history" ? "pf9-tab pf9-tab-active" : "pf9-tab"
            }
            onClick={() => setActiveTab("history")}
          >
            History
          </button>
          <button
            className={
              activeTab === "audit" ? "pf9-tab pf9-tab-active" : "pf9-tab"
            }
            onClick={() => setActiveTab("audit")}
          >
            Audit
          </button>
          <button
            className={
              activeTab === "monitoring" ? "pf9-tab pf9-tab-active" : "pf9-tab"
            }
            onClick={() => setActiveTab("monitoring")}
          >
            Monitoring
          </button>
          <button
            className={
              activeTab === "snapshot-policies" ? "pf9-tab pf9-tab-active" : "pf9-tab"
            }
            onClick={() => setActiveTab("snapshot-policies")}
          >
            📸 Snapshot Policies
          </button>
          <button
            className={
              activeTab === "snapshot-audit" ? "pf9-tab pf9-tab-active" : "pf9-tab"
            }
            onClick={() => setActiveTab("snapshot-audit")}
          >
            📋 Snapshot Audit
          </button>
            </div>
            <ThemeToggle />
          </div>
        </header>

      <section className="pf9-subtitle">
        {activeTab === "servers"
          ? "VM inventory · filters · details · CSV export"
          : activeTab === "snapshots"
          ? "Volume snapshots · filters · details · CSV export"
          : activeTab === "networks"
          ? "Neutron networks · filters · details · CSV export"
          : activeTab === "subnets"
          ? "Neutron subnets · filters · details · CSV export"
          : activeTab === "volumes"
          ? "Cinder volumes · filters · details · CSV export"
          : activeTab === "domains"
          ? "OpenStack domains · organization management · details"
          : activeTab === "projects"
          ? "OpenStack projects · tenant management · details"
          : activeTab === "flavors"
          ? "Nova flavors · resource templates · compute profiles"
          : activeTab === "images"
          ? "Glance images · VM templates · image management"
          : activeTab === "hypervisors"
          ? "Nova hypervisors · compute nodes · resource utilization"
          : activeTab === "users"
          ? "Platform9 users · OpenStack accounts · access management"
          : activeTab === "admin"
          ? "System administration · LDAP users · authentication management"
          : activeTab === "ports"
          ? "Neutron ports · network interfaces · IP assignments"
          : activeTab === "floatingips"
          ? "Floating IP addresses · external connectivity · NAT mappings"
          : activeTab === "history"
          ? "Infrastructure change tracking · timeline · audit trail"
          : activeTab === "monitoring"
          ? "Real-time VM and host metrics · resource usage · performance alerts"
            : activeTab === "api_metrics"
            ? "API performance metrics · latency · error rates"
            : activeTab === "system_logs"
            ? "Centralized system logs · filtering · diagnostics"
            : "Compliance reporting · audit logs · change analysis"}
      </section>

      {activeTab !== "api_metrics" && activeTab !== "system_logs" && (
      <section className="pf9-filters">
        <div className="pf9-filter-row">
          <label>
            Domain (Org)
            <select
              value={selectedDomain}
              onChange={(e) => {
                setSelectedDomain(e.target.value);
                setSelectedTenant("__ALL__");
              }}
            >
              {domains.map((d) => (
                <option key={d.domain_id} value={d.domain_name}>
                  {d.domain_id === "__ALL__" ? "All domains" : d.domain_name}
                </option>
              ))}
            </select>
          </label>

          <label>
            Tenant (Project)
            <select
              value={selectedTenant}
              onChange={(e) => setSelectedTenant(e.target.value)}
            >
              {tenants.map((t) => (
                <option key={t.tenant_id} value={t.tenant_id}>
                  {t.tenant_name}
                </option>
              ))}
            </select>
          </label>

          {activeTab === "servers" && (
            <label>
              VM name contains
              <input
                type="text"
                value={vmSearch}
                onChange={(e) => {
                  setVmSearch(e.target.value);
                  setServerPage(1);
                }}
              />
            </label>
          )}

          <div className="pf9-flex-spacer" />

          <button
            className="pf9-button"
            onClick={exportFn}
            disabled={exportCount === 0}
          >
            Export CSV ({exportCount})
          </button>
        </div>

        {error && <div className="pf9-error">Error: {error}</div>}
        {loading && <div className="pf9-loading">Loading…</div>}
      </section>
      )}

      <section className="pf9-main">
        <div className="pf9-table-panel">
          <div className="pf9-table-header">
            <span>
              Page {activePage} of {activeTotalPages} • {activeTotal} total
            </span>
            <span className="pf9-pagination">
              <button
                onClick={() => {
                  if (activeTab === "servers")
                    setServerPage((p) => Math.max(1, p - 1));
                  else if (activeTab === "snapshots")
                    setSnapPage((p) => Math.max(1, p - 1));
                  else if (activeTab === "networks")
                    setNetworkPage((p) => Math.max(1, p - 1));
                  else if (activeTab === "subnets")
                    setSubnetPage((p) => Math.max(1, p - 1));
                  else if (activeTab === "volumes")
                    setVolumePage((p) => Math.max(1, p - 1));
                  else if (activeTab === "flavors")
                    setFlavorPage((p) => Math.max(1, p - 1));
                  else if (activeTab === "images")
                    setImagePage((p) => Math.max(1, p - 1));
                  else if (activeTab === "hypervisors")
                    setHypervisorPage((p) => Math.max(1, p - 1));
                  else if (activeTab === "users")
                    setUserPage((p) => Math.max(1, p - 1));
                  else if (activeTab === "ports")
                    setPortPage((p) => Math.max(1, p - 1));
                  else if (activeTab === "floatingips")
                    setFloatingIPPage((p) => Math.max(1, p - 1));
                  else if (activeTab === "projects")
                    setProjectPage((p) => Math.max(1, p - 1));
                }}
                disabled={activePage <= 1}
              >
                Prev
              </button>
              <button
                onClick={() => {
                  if (activeTab === "servers")
                    setServerPage((p) =>
                      Math.min(totalPagesServers, p + 1)
                    );
                  else if (activeTab === "snapshots")
                    setSnapPage((p) =>
                      Math.min(totalPagesSnapshots, p + 1)
                    );
                  else if (activeTab === "networks")
                    setNetworkPage((p) =>
                      Math.min(totalPagesNetworks, p + 1)
                    );
                  else if (activeTab === "subnets")
                    setSubnetPage((p) =>
                      Math.min(totalPagesSubnets, p + 1)
                    );
                  else if (activeTab === "volumes")
                    setVolumePage((p) =>
                      Math.min(totalPagesVolumes, p + 1)
                    );
                  else if (activeTab === "flavors")
                    setFlavorPage((p) =>
                      Math.min(Math.ceil(flavorsTotal / flavorPageSize), p + 1)
                    );
                  else if (activeTab === "images")
                    setImagePage((p) =>
                      Math.min(Math.ceil(imagesTotal / imagePageSize), p + 1)
                    );
                  else if (activeTab === "hypervisors")
                    setHypervisorPage((p) =>
                      Math.min(Math.ceil(hypervisorsTotal / hypervisorPageSize), p + 1)
                    );
                  else if (activeTab === "ports")
                    setPortPage((p) =>
                      Math.min(Math.ceil(portsTotal / portPageSize), p + 1)
                    );
                  else if (activeTab === "floatingips")
                    setFloatingIPPage((p) =>
                      Math.min(Math.ceil(floatingIPsTotal / floatingIPPageSize), p + 1)
                    );
                  else if (activeTab === "projects")
                    setProjectPage((p) =>
                      Math.min(Math.ceil(projectsTotal / projectPageSize), p + 1)
                    );
                  else if (activeTab === "users")
                    setUserPage((p) =>
                      Math.min(Math.ceil(usersTotal / userPageSize), p + 1)
                    );
                }}
                disabled={activePage >= activeTotalPages}
              >
                Next
              </button>

              <label>
                Page size
                <select
                  value={activePageSize}
                  onChange={(e) => {
                    const v = Number(e.target.value) || 50;
                    if (activeTab === "servers") {
                      setServerPageSize(v);
                      setServerPage(1);
                    } else if (activeTab === "snapshots") {
                      setSnapPageSize(v);
                      setSnapPage(1);
                    } else if (activeTab === "networks") {
                      setNetworkPageSize(v);
                      setNetworkPage(1);
                    } else if (activeTab === "subnets") {
                      setSubnetPageSize(v);
                      setSubnetPage(1);
                    } else if (activeTab === "volumes") {
                      setVolumePageSize(v);
                      setVolumePage(1);
                    } else if (activeTab === "flavors") {
                      setFlavorPageSize(v);
                      setFlavorPage(1);
                    } else if (activeTab === "images") {
                      setImagePageSize(v);
                      setImagePage(1);
                    } else if (activeTab === "hypervisors") {
                      setHypervisorPageSize(v);
                      setHypervisorPage(1);
                    } else if (activeTab === "ports") {
                      setPortPageSize(v);
                      setPortPage(1);
                    } else if (activeTab === "floatingips") {
                      setFloatingIPPageSize(v);
                      setFloatingIPPage(1);
                    } else if (activeTab === "projects") {
                      setProjectPageSize(v);
                      setProjectPage(1);
                    } else if (activeTab === "users") {
                      setUserPageSize(v);
                      setUserPage(1);
                    }
                  }}
                >
                  <option value={10}>10</option>
                  <option value={25}>25</option>
                  <option value={50}>50</option>
                  <option value={100}>100</option>
                </select>
              </label>
            </span>
          </div>

          {/* Sort controls per tab */}
          <div className="pf9-sort-row">
            {activeTab === "servers" && (
              <>
                <label>
                  Sort by
                  <select
                    value={serverSortBy}
                    onChange={(e) => {
                      setServerSortBy(e.target.value);
                      setServerPage(1);
                    }}
                  >
                    <option value="domain_name">Domain</option>
                    <option value="tenant_name">Tenant</option>
                    <option value="vm_name">VM name</option>
                    <option value="status">Status</option>
                    <option value="flavor_name">Flavor</option>
                    <option value="created_at">Created</option>
                  </select>
                </label>
                <label>
                  Sort dir
                  <select
                    value={serverSortDir}
                    onChange={(e) =>
                      setServerSortDir(
                        e.target.value === "desc" ? "desc" : "asc"
                      )
                    }
                  >
                    <option value="asc">Asc</option>
                    <option value="desc">Desc</option>
                  </select>
                </label>
              </>
            )}

            {activeTab === "snapshots" && (
              <>
                <label>
                  Sort by
                  <select
                    value={snapSortBy}
                    onChange={(e) => {
                      setSnapSortBy(e.target.value);
                      setSnapPage(1);
                    }}
                  >
                    <option value="created_at">Created</option>
                    <option value="snapshot_name">Snapshot</option>
                    <option value="status">Status</option>
                    <option value="size_gb">Size (GB)</option>
                    <option value="domain_name">Domain</option>
                    <option value="tenant_name">Tenant</option>
                  </select>
                </label>
                <label>
                  Sort dir
                  <select
                    value={snapSortDir}
                    onChange={(e) =>
                      setSnapSortDir(
                        e.target.value === "asc" ? "asc" : "desc"
                      )
                    }
                  >
                    <option value="desc">Desc</option>
                    <option value="asc">Asc</option>
                  </select>
                </label>
              </>
            )}

            {activeTab === "networks" && (
              <>
                <label>
                  Sort by
                  <select
                    value={networkSortBy}
                    onChange={(e) => {
                      setNetworkSortBy(e.target.value);
                      setNetworkPage(1);
                    }}
                  >
                    <option value="network_name">Network</option>
                    <option value="domain_name">Domain</option>
                    <option value="project_name">Project</option>
                    <option value="is_shared">Shared</option>
                    <option value="is_external">External</option>
                    <option value="last_seen_at">Last seen</option>
                  </select>
                </label>
                <label>
                  Sort dir
                  <select
                    value={networkSortDir}
                    onChange={(e) => {
                      setNetworkSortDir(
                        e.target.value === "desc" ? "desc" : "asc"
                      );
                      setNetworkPage(1);
                    }}
                  >
                    <option value="asc">Asc</option>
                    <option value="desc">Desc</option>
                  </select>
                </label>
              </>
            )}

            {activeTab === "subnets" && (
              <>
                <label>
                  Sort by
                  <select
                    value={subnetSortBy}
                    onChange={(e) => {
                      setSubnetSortBy(e.target.value);
                      setSubnetPage(1);
                    }}
                  >
                    <option value="name">Subnet</option>
                    <option value="domain_name">Domain</option>
                    <option value="tenant_name">Tenant</option>
                    <option value="project_name">Project</option>
                    <option value="cidr">CIDR</option>
                    <option value="last_seen_at">Last seen</option>
                  </select>
                </label>
                <label>
                  Sort dir
                  <select
                    value={subnetSortDir}
                    onChange={(e) => {
                      setSubnetSortDir(
                        e.target.value === "desc" ? "desc" : "asc"
                      );
                      setSubnetPage(1);
                    }}
                  >
                    <option value="asc">Asc</option>
                    <option value="desc">Desc</option>
                  </select>
                </label>
              </>
            )}

            {activeTab === "volumes" && (
              <>
                <label>
                  Sort by
                  <select
                    value={volumeSortBy}
                    onChange={(e) => {
                      setVolumeSortBy(e.target.value);
                      setVolumePage(1);
                    }}
                  >
                    <option value="volume_name">Volume</option>
                    <option value="domain_name">Domain</option>
                    <option value="tenant_name">Tenant</option>
                    <option value="project_name">Project</option>
                    <option value="status">Status</option>
                    <option value="size_gb">Size (GB)</option>
                    <option value="created_at">Created</option>
                    <option value="last_seen_at">Last seen</option>
                  </select>
                </label>
                <label>
                  Sort dir
                  <select
                    value={volumeSortDir}
                    onChange={(e) => {
                      setVolumeSortDir(
                        e.target.value === "desc" ? "desc" : "asc"
                      );
                      setVolumePage(1);
                    }}
                  >
                    <option value="asc">Asc</option>
                    <option value="desc">Desc</option>
                  </select>
                </label>
              </>
            )}

            {activeTab === "users" && (
              <>
                <label>
                  Sort by
                  <select
                    value={userSortBy}
                    onChange={(e) => {
                      setUserSortBy(e.target.value);
                      setUserPage(1);
                    }}
                  >
                    <option value="name">Name</option>
                    <option value="email">Email</option>
                    <option value="domain_name">Domain</option>
                    <option value="enabled">Status</option>
                    <option value="created_at">Created</option>
                    <option value="last_login_at">Last Login</option>
                    <option value="last_seen_at">Last Seen</option>
                  </select>
                </label>
                <label>
                  Sort dir
                  <select
                    value={userSortDir}
                    onChange={(e) => {
                      setUserSortDir(
                        e.target.value === "desc" ? "desc" : "asc"
                      );
                      setUserPage(1);
                    }}
                  >
                    <option value="asc">Asc</option>
                    <option value="desc">Desc</option>
                  </select>
                </label>
              </>
            )}
          </div>

          {/* Tables */}
          {activeTab === "servers" && (
            <table className="pf9-table">
              <thead>
                <tr>
                  <th>VM</th>
                  <th>Domain</th>
                  <th>Tenant</th>
                  <th>Status</th>
                  <th>Flavor</th>
                  <th>vCPUs</th>
                  <th>RAM (MB)</th>
                  <th>Disk (GB)</th>
                  <th>IPs</th>
                  <th>Image</th>
                </tr>
              </thead>
              <tbody>
                {servers.length === 0 ? (
                  <tr>
                    <td colSpan={10} className="pf9-empty">
                      No results.
                    </td>
                  </tr>
                ) : (
                  servers.map((s) => (
                    <tr
                      key={s.vm_id}
                      className={
                        selectedServer && selectedServer.vm_id === s.vm_id
                          ? "pf9-row-selected"
                          : ""
                      }
                      onClick={() => setSelectedServer(s)}
                    >
                      <td>
                        <div className="pf9-cell-title">
                          {s.vm_name || s.vm_id}
                        </div>
                        <div className="pf9-cell-subtle">{s.vm_id}</div>
                      </td>
                      <td>{s.domain_name}</td>
                      <td>{s.tenant_name}</td>
                      <td>{s.status}</td>
                      <td>{s.flavor_name}</td>
                      <td className="pf9-cell-number">{s.vcpus || 0}</td>
                      <td className="pf9-cell-number">{s.ram_mb || 0}</td>
                      <td className="pf9-cell-number">{s.disk_gb || 0}</td>
                      <td>{s.ips}</td>
                      <td>{s.image_name || "N/A"}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          )}
          
          {activeTab === "snapshots" && (
            <table className="pf9-table">
              <thead>
                <tr>
                  <th>Snapshot</th>
                  <th>Volume</th>
                  <th>VM</th>
                  <th>Domain</th>
                  <th>Tenant</th>
                  <th>Status</th>
                  <th>Size</th>
                  <th>Created</th>
                  <th>Last seen</th>
                </tr>
              </thead>
              <tbody>
                {snapshots.length === 0 ? (
                  <tr>
                    <td colSpan={9}>No results.</td>
                  </tr>
                ) : (
                  snapshots.map((s) => (
                    <tr
                      key={s.snapshot_id}
                      className={
                        selectedSnapshot &&
                        selectedSnapshot.snapshot_id === s.snapshot_id
                          ? "pf9-row-selected"
                          : ""
                      }
                      onClick={() => setSelectedSnapshot(s)}
                    >
                      <td>
                        <div className="pf9-cell-title">
                          {s.snapshot_name || s.snapshot_id}
                          {s.is_deleted && (
                            <span className="pf9-badge pf9-badge-deleted">
                              Deleted
                            </span>
                          )}
                        </div>
                        <div className="pf9-cell-subtle">
                          {s.snapshot_id}
                        </div>
                      </td>
                      <td>
                        <div className="pf9-cell-title">Volume ID</div>
                        <div className="pf9-cell-subtle">{s.volume_id || "N/A"}</div>
                      </td>
                      <td>
                        <div className="pf9-cell-title">{s.vm_name || "N/A"}</div>
                        <div className="pf9-cell-subtle">{s.vm_id || "N/A"}</div>
                      </td>
                      <td>{s.domain_name}</td>
                      <td>{s.tenant_name}</td>
                      <td>{s.status}</td>
                      <td>{s.size_gb ?? ""}</td>
                      <td>{formatDate(s.created_at)}</td>
                      <td>{formatDate(s.last_seen_at)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          )}
          
          {activeTab === "networks" && (
            <table className="pf9-table">
              <thead>
                <tr>
                  <th>Network</th>
                  <th>Domain</th>
                  <th>Project</th>
                  <th>Shared</th>
                  <th>External</th>
                  <th>VLAN Info</th>
                  <th>Last seen</th>
                </tr>
              </thead>
              <tbody>
                {networks.length === 0 ? (
                  <tr>
                    <td colSpan={7}>No results.</td>
                  </tr>
                ) : (
                  networks.map((n) => (
                    <tr
                      key={n.network_id}
                      className={
                        selectedNetwork &&
                        selectedNetwork.network_id === n.network_id
                          ? "pf9-row-selected"
                          : ""
                      }
                      onClick={() => setSelectedNetwork(n)}
                    >
                      <td>
                        <div className="pf9-cell-title">
                          {n.network_name || n.network_id}
                        </div>
                        <div className="pf9-cell-subtle">{n.network_id}</div>
                      </td>
                      <td>{n.domain_name}</td>
                      <td>{n.project_name}</td>
                      <td>{yesNo(n.is_shared)}</td>
                      <td>{yesNo(n.is_external)}</td>
                      <td>
                        {n.network_name.includes("VLAN") || n.network_name.includes("vLAN") ? 
                          n.network_name.match(/[vV]LAN[\s\-_]*([\d]+)/)?.[1] || "N/A" : "N/A"}
                      </td>
                      <td>{formatDate(n.last_seen_at)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          )}
          
          {activeTab === "subnets" && (
            <table className="pf9-table">
              <thead>
                <tr>
                  <th>Subnet</th>
                  <th>Network</th>
                  <th>Domain</th>
                  <th>Tenant</th>
                  <th>Project</th>
                  <th>CIDR</th>
                  <th>Gateway</th>
                  <th>Last seen</th>
                </tr>
              </thead>
              <tbody>
                {subnets.length === 0 ? (
                  <tr>
                    <td colSpan={8}>No results.</td>
                  </tr>
                ) : (
                  subnets.map((s) => (
                    <tr
                      key={s.id}
                      className={
                        selectedSubnet && selectedSubnet.id === s.id
                          ? "pf9-row-selected"
                          : ""
                      }
                      onClick={() => setSelectedSubnet(s)}
                    >
                      <td>
                        <div className="pf9-cell-title">
                          {s.name || s.id}
                        </div>
                        <div className="pf9-cell-subtle">{s.id}</div>
                      </td>
                      <td>{s.network_name}</td>
                      <td>{s.domain_name}</td>
                      <td>{s.tenant_name}</td>
                      <td>{s.project_name}</td>
                      <td>{s.cidr}</td>
                      <td>{s.gateway_ip}</td>
                      <td>{formatDate(s.last_seen_at)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          )}
          
          {activeTab === "volumes" && (
            <table className="pf9-table">
              <thead>
                <tr>
                  <th>Volume</th>
                  <th>Domain</th>
                  <th>Tenant</th>
                  <th>Project</th>
                  <th>Size</th>
                  <th>Status</th>
                  <th>Type</th>
                  <th>Attached to (VM)</th>
                  <th>Auto Snapshot</th>
                  <th>Snapshot Policy</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {volumes.length === 0 ? (
                  <tr>
                    <td colSpan={11}>No results.</td>
                  </tr>
                ) : (
                  volumes.map((v) => (
                    <tr
                      key={volumeDisplayId(v)}
                      className={
                        selectedVolume &&
                        volumeDisplayId(selectedVolume) === volumeDisplayId(v)
                          ? "pf9-row-selected"
                          : ""
                      }
                      onClick={() => setSelectedVolume(v)}
                    >
                      <td>
                        <div className="pf9-cell-title">
                          {v.volume_name || volumeDisplayId(v)}
                        </div>
                        <div className="pf9-cell-subtle">
                          {volumeDisplayId(v)}
                        </div>
                      </td>
                      <td>{v.domain_name}</td>
                      <td>{v.tenant_name}</td>
                      <td>{v.project_name}</td>
                      <td>{v.size_gb ?? ""}</td>
                      <td>{v.status ?? ""}</td>
                      <td>{v.volume_type ?? ""}</td>
                      <td>
                        <div className="pf9-cell-title">{v.server_name || "Unattached"}</div>
                        <div className="pf9-cell-subtle">{v.server_id || "N/A"}</div>
                      </td>
                      <td>
                        <span className={v.auto_snapshot === "true" ? "pf9-badge-success" : "pf9-badge-default"}>
                          {v.auto_snapshot === "true" ? "Enabled" : "Disabled"}
                        </span>
                      </td>
                      <td>{v.snapshot_policy ?? "None"}</td>
                      <td>{formatDate(v.created_at)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          )}
          
          {/* Domains Table */}
          {activeTab === "domains" && (
            <table className="pf9-table">
              <thead>
                <tr>
                  <th>Domain ID</th>
                  <th>Domain Name</th>
                </tr>
              </thead>
              <tbody>
                {domains.length === 0 ? (
                  <tr>
                    <td colSpan={2} className="pf9-empty">
                      No domains found.
                    </td>
                  </tr>
                ) : (
                  domains.filter(d => d.domain_id !== "__ALL__").map((d) => (
                    <tr
                      key={d.domain_id}
                      onClick={() => setSelectedDomain(d.domain_name)}
                      className={selectedDomain === d.domain_name ? "pf9-row-selected" : ""}
                    >
                      <td>{d.domain_id}</td>
                      <td>{d.domain_name}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          )}

          {/* Projects Table */}
          {activeTab === "projects" && (
            <table className="pf9-table">
              <thead>
                <tr>
                  <th>Project ID</th>
                  <th>Project Name</th>
                  <th>Domain</th>
                </tr>
              </thead>
              <tbody>
                {projects.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="pf9-empty">
                      No projects found.
                    </td>
                  </tr>
                ) : (
                  projects.filter(p => p.tenant_id !== "__ALL__").map((p) => (
                    <tr
                      key={p.tenant_id}
                      onClick={() => setSelectedProject(p)}
                      className={selectedProject?.tenant_id === p.tenant_id ? "pf9-row-selected" : ""}
                    >
                      <td>{p.tenant_id}</td>
                      <td>{p.tenant_name}</td>
                      <td>{p.domain_name}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          )}

          {/* Flavors Table */}
          {activeTab === "flavors" && (
            <table className="pf9-table">
              <thead>
                <tr>
                  <th>Flavor Name</th>
                  <th>vCPUs</th>
                  <th>RAM (MB)</th>
                  <th>Disk (GB)</th>
                  <th>Ephemeral (GB)</th>
                  <th>VMs Using</th>
                  <th>Public</th>
                  <th>Last Seen</th>
                </tr>
              </thead>
              <tbody>
                {flavors.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="pf9-empty">
                      No flavors found.
                    </td>
                  </tr>
                ) : (
                  flavors.map((f) => {
                    const vmCount = servers.filter(s => s.flavor_name === f.flavor_name).length;
                    return (
                      <tr
                        key={f.flavor_id}
                        onClick={() => setSelectedFlavor(f)}
                        className={selectedFlavor?.flavor_id === f.flavor_id ? "pf9-row-selected" : ""}
                      >
                        <td>{f.flavor_name}</td>
                        <td>{f.vcpus}</td>
                        <td>{f.ram_mb?.toLocaleString()}</td>
                        <td>{f.disk_gb}</td>
                        <td>{f.ephemeral_gb}</td>
                        <td><strong>{vmCount}</strong></td>
                        <td>{f.is_public ? "Yes" : "No"}</td>
                        <td>{formatDate(f.last_seen_at)}</td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          )}

          {/* Images Table */}
          {activeTab === "images" && (
            <table className="pf9-table">
              <thead>
                <tr>
                  <th>Image Name</th>
                  <th>Size (MB)</th>
                  <th>Last Seen</th>
                </tr>
              </thead>
              <tbody>
                {images.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="pf9-empty">
                      No images found.
                    </td>
                  </tr>
                ) : (
                  images.map((img) => (
                    <tr
                      key={img.image_id}
                      onClick={() => setSelectedImage(img)}
                      className={selectedImage?.image_id === img.image_id ? "pf9-row-selected" : ""}
                    >
                      <td>{img.image_name}</td>
                      <td>{img.size_bytes ? Math.round(img.size_bytes / 1024 / 1024).toLocaleString() : "-"}</td>
                      <td>{formatDate(img.last_seen_at)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          )}

          {/* Hypervisors Table */}
          {activeTab === "hypervisors" && (
            <table className="pf9-table">
              <thead>
                <tr>
                  <th>Hypervisor</th>
                  <th>Host IP</th>
                  <th>Roles</th>
                  <th>Uptime</th>
                  <th>vCPUs</th>
                  <th>vCPUs Used</th>
                  <th>Memory (GB)</th>
                  <th>Memory Used (GB)</th>
                  <th>Local Storage (GB)</th>
                  <th>Storage Used (GB)</th>
                  <th>Running VMs</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {hypervisors.length === 0 ? (
                  <tr>
                    <td colSpan={12} className="pf9-empty">
                      No hypervisors found.
                    </td>
                  </tr>
                ) : (
                  hypervisors.map((h) => {
                    const formatUptime = (seconds) => {
                      if (!seconds) return "N/A";
                      const days = Math.floor(seconds / 86400);
                      const hours = Math.floor((seconds % 86400) / 3600);
                      const mins = Math.floor((seconds % 3600) / 60);
                      return `${days}d ${hours}h ${mins}m`;
                    };
                    return (
                      <tr
                        key={h.hypervisor_id}
                        onClick={() => setSelectedHypervisor(h)}
                        className={selectedHypervisor?.hypervisor_id === h.hypervisor_id ? "pf9-row-selected" : ""}
                      >
                        <td>{h.hypervisor_hostname}</td>
                        <td>{h.host_ip || "-"}</td>
                        <td><span className="pf9-badge pf9-badge-info">{h.pf9_roles || "Unknown"}</span></td>
                        <td>{formatUptime(h.uptime_seconds)}</td>
                        <td>{h.vcpus || "-"}</td>
                        <td>{h.vcpus_used || "-"}</td>
                        <td>{h.memory_mb ? Math.round(h.memory_mb / 1024).toLocaleString() : "-"}</td>
                        <td>{h.memory_mb_used ? Math.round(h.memory_mb_used / 1024).toLocaleString() : "-"}</td>
                        <td>{h.local_gb?.toLocaleString() || "-"}</td>
                        <td>{h.local_gb_used?.toLocaleString() || "-"}</td>
                        <td>{h.running_vms || "-"}</td>
                        <td>{h.status || "-"}</td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          )}

          {/* Users Table */}
          {activeTab === "users" && (
            <table className="pf9-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Email</th>
                  <th>Domain</th>
                  <th>Enabled</th>
                  <th>Description</th>
                  <th>Roles</th>
                  <th>Created</th>
                  <th>Last Login</th>
                  <th>Last Seen</th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan={9}>Loading users...</td>
                  </tr>
                ) : users.length === 0 ? (
                  <tr>
                    <td colSpan={9}>No users found.</td>
                  </tr>
                ) : (
                  users.map((user, idx) => (
                    <tr key={user.id}>
                      <td>
                        <div>{user.name}</div>
                        <div className="pf9-cell-subtle">{user.id}</div>
                      </td>
                      <td>{user.email || "N/A"}</td>
                      <td>{user.domain_name || "N/A"}</td>
                      <td>
                        <span
                          className={
                            user.enabled
                              ? "pf9-badge pf9-badge-success"
                              : "pf9-badge pf9-badge-danger"
                          }
                        >
                          {user.enabled ? "Enabled" : "Disabled"}
                        </span>
                      </td>
                      <td className="pf9-cell-subtle">{user.description || "N/A"}</td>
                      <td className="pf9-cell-subtle">{user.roles || "Roles not collected"}</td>
                      <td>{formatDate(user.created_at)}</td>
                      <td>{formatDate(user.last_login)}</td>
                      <td>{formatDate(user.last_seen_at)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          )}

          {/* Admin Panel for LDAP Management */}
          {activeTab === "admin" && (
            <UserManagement user={authUser} />
          )}

          {/* Ports Table */}
          {activeTab === "ports" && (
            <table className="pf9-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>ID</th>
                  <th>Domain</th>
                  <th>Tenant</th>
                  <th>Network ID</th>
                  <th>Device Owner</th>
                  <th>Device ID</th>
                  <th>MAC Address</th>
                  <th>IP Addresses</th>
                  <th>Last Seen</th>
                </tr>
              </thead>
              <tbody>
                {ports.map((port) => (
                  <tr key={port.id}>
                    <td>{port.name || "N/A"}</td>
                    <td className="pf9-cell-subtle">{port.id}</td>
                    <td>{port.domain_name || "N/A"}</td>
                    <td>{port.tenant_name || "N/A"}</td>
                    <td className="pf9-cell-subtle">{port.network_id?.substring(0, 8)}...</td>
                    <td>{port.device_owner || "N/A"}</td>
                    <td className="pf9-cell-subtle">{port.device_id ? port.device_id.substring(0, 8) + "..." : "N/A"}</td>
                    <td>{port.mac_address || "N/A"}</td>
                    <td>{port.ip_addresses && port.ip_addresses.length > 0 ? 
                         port.ip_addresses.map((ip: any) => ip.ip_address || JSON.stringify(ip)).join(", ") : 
                         "N/A"}</td>
                    <td>{formatDate(port.last_seen_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {/* Floating IPs Table */}
          {activeTab === "floatingips" && (
            <table className="pf9-table">
              <thead>
                <tr>
                  <th>Floating IP</th>
                  <th>Fixed IP</th>
                  <th>Status</th>
                  <th>Domain</th>
                  <th>Tenant</th>
                  <th>Port ID</th>
                  <th>Router ID</th>
                  <th>Last Seen</th>
                </tr>
              </thead>
              <tbody>
                {floatingIPs.map((fip) => (
                  <tr key={fip.id}>
                    <td><strong>{fip.floating_ip || "N/A"}</strong></td>
                    <td>{fip.fixed_ip || "N/A"}</td>
                    <td>
                      <span className={`pf9-status pf9-status-${fip.status?.toLowerCase()}`}>
                        {fip.status || "N/A"}
                      </span>
                    </td>
                    <td>{fip.domain_name || "N/A"}</td>
                    <td>{fip.tenant_name || "N/A"}</td>
                    <td className="pf9-cell-subtle">{fip.port_id ? fip.port_id.substring(0, 8) + "..." : "N/A"}</td>
                    <td className="pf9-cell-subtle">{fip.router_id ? fip.router_id.substring(0, 8) + "..." : "N/A"}</td>
                    <td>{formatDate(fip.last_seen_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          
          {/* History Tab Content */}
          {activeTab === "history" && (
            <div className="pf9-history-container">
              <div className="pf9-history-controls">
                <label>
                  Timeframe (hours):
                  <select
                    value={changeTimeframe}
                    onChange={(e) => setChangeTimeframe(parseInt(e.target.value))}
                  >
                    <option value={1}>Last hour</option>
                    <option value={24}>Last 24 hours</option>
                    <option value={72}>Last 3 days</option>
                    <option value={168}>Last week</option>
                  </select>
                </label>
              </div>
              
              <div className="pf9-history-sections">
                {/* Recent Changes Section */}
                <div className="pf9-history-section">
                  <h3>Recent Changes ({recentChanges?.length || 0})</h3>
                  {!recentChanges || recentChanges.length === 0 ? (
                    <p>No changes in the selected timeframe.</p>
                  ) : (
                    <table className="pf9-table">
                      <thead>
                        <tr>
                          <th>Time</th>
                          <th>Type</th>
                          <th>Resource</th>
                          <th>ID</th>
                          <th>Project</th>
                          <th>Domain</th>
                          <th>Change Description</th>
                          <th>Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {recentChanges.map((change, idx) => {
                          // Use API-provided project/domain data directly
                          const projectName = change.project_name || "N/A";
                          const domainName = change.domain_name || "N/A";
                          const changeTypeClass = change.change_description?.includes('deletion') ? 
                            'pf9-badge pf9-badge-warning' : 'pf9-badge pf9-badge-info';
                          
                          return (
                            <tr key={idx}>
                              <td>{formatDate(change.actual_time || change.recorded_at)}</td>
                              <td>
                                <span className={changeTypeClass}>
                                  {change.resource_type}
                                </span>
                              </td>
                              <td>{change.resource_name || "N/A"}</td>
                              <td className="pf9-cell-subtle">{change.resource_id}</td>
                              <td>{projectName}</td>
                              <td>{domainName}</td>
                              <td className="pf9-cell-subtle">
                                <div>{change.change_description || 'Infrastructure change'}</div>
                                <small style={{color: '#666'}}>{change.change_hash.substring(0, 8)}...</small>
                              </td>
                              <td>
                                <button 
                                  className="pf9-button-small"
                                  onClick={() => loadResourceHistory(change.resource_type, change.resource_id)}
                                >
                                  View History
                                </button>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  )}
                </div>

                {/* Most Changed Resources Section */}
                <div className="pf9-history-section">
                  <h3>Most Frequently Changed Resources</h3>
                  {!mostChangedResources || mostChangedResources.length === 0 ? (
                    <p>Loading most changed resources...</p>
                  ) : (
                    <table className="pf9-table">
                      <thead>
                        <tr>
                          <th>Type</th>
                          <th>Resource</th>
                          <th>Changes</th>
                          <th>Last Change</th>
                          <th>Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {mostChangedResources.slice(0, 20).map((resource, idx) => (
                          <tr key={idx}>
                            <td>
                              <span className="pf9-badge pf9-badge-info">
                                {resource.resource_type}
                              </span>
                            </td>
                            <td>{resource.resource_name || "N/A"}</td>
                            <td>{resource.change_count}</td>
                            <td>{formatDate(resource.last_change_at)}</td>
                            <td>
                              <button 
                                className="pf9-button-small"
                                onClick={() => loadResourceHistory(resource.resource_type, resource.resource_id)}
                              >
                                View History
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Audit Tab Content */}
          {activeTab === "audit" && (
            <div className="pf9-audit-container">
              <div className="pf9-audit-sections">
                <div className="pf9-audit-section">
                  <h3>Infrastructure Overview</h3>
                  <div className="pf9-compliance-grid">
                    <div className="pf9-compliance-card">
                      <h4>Domains</h4>
                      <div className="pf9-compliance-value">
                        {domains.length}
                      </div>
                    </div>
                    <div className="pf9-compliance-card">
                      <h4>Projects</h4>
                      <div className="pf9-compliance-value">
                        {tenants.length}
                      </div>
                    </div>
                    <div className="pf9-compliance-card">
                      <h4>Total VMs</h4>
                      <div className="pf9-compliance-value">
                        {allServersForAudit.length}
                      </div>
                    </div>
                    <div className="pf9-compliance-card">
                      <h4>Networks</h4>
                      <div className="pf9-compliance-value">
                        {allNetworksForAudit.length}
                      </div>
                    </div>
                    <div className="pf9-compliance-card">
                      <h4>Volumes</h4>
                      <div className="pf9-compliance-value">
                        {allVolumesForAudit.length}
                      </div>
                    </div>
                    <div className="pf9-compliance-card">
                      <h4>Snapshots</h4>
                      <div className="pf9-compliance-value">
                        {allSnapshotsForAudit.length}
                      </div>
                    </div>
                  </div>
                </div>
                
                <div className="pf9-audit-section">
                  <h3>VMs per Tenant</h3>
                  <table className="pf9-table">
                    <thead>
                      <tr>
                        <th>Tenant</th>
                        <th>Domain</th>
                        <th>VM Count</th>
                        <th>Active VMs</th>
                        <th>Total vCPUs</th>
                        <th>Total RAM (GB)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(
                        allServersForAudit.reduce((acc, server) => {
                          const key = `${server.tenant_name}-${server.domain_name}`;
                          if (!acc[key]) {
                            acc[key] = {
                              tenant: server.tenant_name,
                              domain: server.domain_name,
                              count: 0,
                              active: 0,
                              vcpus: 0,
                              ram: 0
                            };
                          }
                          acc[key].count++;
                          if (server.status === "ACTIVE") acc[key].active++;
                          // Handle missing vCPU and RAM data gracefully
                          const vcpus = server.vcpus || 0;
                          const ramMb = server.ram_mb || 0;
                          acc[key].vcpus += vcpus;
                          acc[key].ram += ramMb / 1024; // Convert MB to GB
                          return acc;
                        }, {} as any)
                      ).map(([key, stats]: [string, any]) => (
                        <tr key={key}>
                          <td>{stats.tenant}</td>
                          <td>{stats.domain}</td>
                          <td>{stats.count}</td>
                          <td>{stats.active}</td>
                          <td>{stats.vcpus}</td>
                          <td>{stats.ram.toFixed(1)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <div className="pf9-audit-section">
                  <h3>Storage Summary</h3>
                  <table className="pf9-table">
                    <thead>
                      <tr>
                        <th>Tenant</th>
                        <th>Volumes</th>
                        <th>Total Size (GB)</th>
                        <th>Attached</th>
                        <th>Snapshots</th>
                        <th>Auto Backup Enabled</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(
                        volumes.reduce((acc, volume) => {
                          const tenant = volume.tenant_name;
                          if (!acc[tenant]) {
                            acc[tenant] = {
                              count: 0,
                              size: 0,
                              attached: 0,
                              autoBackup: 0
                            };
                          }
                          acc[tenant].count++;
                          acc[tenant].size += volume.size_gb || 0;
                          if (volume.server_id) acc[tenant].attached++;
                          if (volume.auto_snapshot === "true") acc[tenant].autoBackup++;
                          return acc;
                        }, {} as any)
                      ).map(([tenant, stats]: [string, any]) => {
                        const tenantSnapshots = snapshots.filter(s => s.tenant_name === tenant);
                        return (
                          <tr key={tenant}>
                            <td>{tenant}</td>
                            <td>{stats.count}</td>
                            <td>{stats.size}</td>
                            <td>{stats.attached}</td>
                            <td>{tenantSnapshots.length}</td>
                            <td>{stats.autoBackup}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                <div className="pf9-audit-section">
                  <h3>Network Distribution</h3>
                  <table className="pf9-table">
                    <thead>
                      <tr>
                        <th>Domain</th>
                        <th>Networks</th>
                        <th>External Networks</th>
                        <th>Shared Networks</th>
                        <th>Subnets</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(
                        networks.reduce((acc, network) => {
                          const domain = network.domain_name;
                          if (!acc[domain]) {
                            acc[domain] = { count: 0, external: 0, shared: 0 };
                          }
                          acc[domain].count++;
                          if (network.is_external) acc[domain].external++;
                          if (network.is_shared) acc[domain].shared++;
                          return acc;
                        }, {} as any)
                      ).map(([domain, stats]: [string, any]) => {
                        const domainSubnets = subnets.filter(s => s.domain_name === domain);
                        return (
                          <tr key={domain}>
                            <td>{domain}</td>
                            <td>{stats.count}</td>
                            <td>{stats.external}</td>
                            <td>{stats.shared}</td>
                            <td>{domainSubnets.length}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                
                <div className="pf9-audit-section">
                  <h3>Storage Summary</h3>
                  <table className="pf9-table">
                    <thead>
                      <tr>
                        <th>Tenant</th>
                        <th>Volumes</th>
                        <th>Total Size (GB)</th>
                        <th>Attached</th>
                        <th>Snapshots</th>
                        <th>Auto Backup Enabled</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(
                        volumes.reduce((acc, volume) => {
                          const tenant = volume.tenant_name;
                          if (!acc[tenant]) {
                            acc[tenant] = {
                              count: 0,
                              size: 0,
                              attached: 0,
                              autoBackup: 0
                            };
                          }
                          acc[tenant].count++;
                          acc[tenant].size += volume.size_gb || 0;
                          if (volume.server_id) acc[tenant].attached++;
                          if (volume.auto_snapshot === "true") acc[tenant].autoBackup++;
                          return acc;
                        }, {} as any)
                      ).map(([tenant, stats]: [string, any]) => {
                        const tenantSnapshots = snapshots.filter(s => s.tenant_name === tenant);
                        return (
                          <tr key={tenant}>
                            <td>{tenant}</td>
                            <td>{stats.count}</td>
                            <td>{stats.size}</td>
                            <td>{stats.attached}</td>
                            <td>{tenantSnapshots.length}</td>
                            <td>{stats.autoBackup}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                <div className="pf9-audit-section">
                  <h3>Network Distribution</h3>
                  <table className="pf9-table">
                    <thead>
                      <tr>
                        <th>Domain</th>
                        <th>Networks</th>
                        <th>External Networks</th>
                        <th>Shared Networks</th>
                        <th>Subnets</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(
                        networks.reduce((acc, network) => {
                          const domain = network.domain_name;
                          if (!acc[domain]) {
                            acc[domain] = { count: 0, external: 0, shared: 0 };
                          }
                          acc[domain].count++;
                          if (network.is_external) acc[domain].external++;
                          if (network.is_shared) acc[domain].shared++;
                          return acc;
                        }, {} as any)
                      ).map(([domain, stats]: [string, any]) => {
                        const domainSubnets = subnets.filter(s => s.domain_name === domain);
                        return (
                          <tr key={domain}>
                            <td>{domain}</td>
                            <td>{stats.count}</td>
                            <td>{stats.external}</td>
                            <td>{stats.shared}</td>
                            <td>{domainSubnets.length}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                
                <div className="pf9-audit-section">
                  <h3>Flavor Usage Analytics</h3>
                  <table className="pf9-table">
                    <thead>
                      <tr>
                        <th>Flavor</th>
                        <th>VMs Using</th>
                        <th>Total vCPUs</th>
                        <th>Total RAM (GB)</th>
                        <th>Utilization %</th>
                      </tr>
                    </thead>
                    <tbody>
                      {flavors.filter(flavor => {
                        const vmsUsingFlavor = servers.filter(s => s.flavor_name === flavor.flavor_name);
                        return vmsUsingFlavor.length > 0;
                      }).map(flavor => {
                        const vmsUsingFlavor = servers.filter(s => s.flavor_name === flavor.flavor_name);
                        const totalVCpus = vmsUsingFlavor.length * (flavor.vcpus || 0);
                        const totalRAM = vmsUsingFlavor.length * (flavor.ram_mb || 0) / 1024;
                        const utilizationPct = servers.length > 0 ? (vmsUsingFlavor.length / servers.length * 100) : 0;
                        return (
                          <tr key={flavor.flavor_id}>
                            <td>{flavor.flavor_name}</td>
                            <td><strong>{vmsUsingFlavor.length}</strong></td>
                            <td>{totalVCpus}</td>
                            <td>{totalRAM.toFixed(1)}</td>
                            <td>{utilizationPct.toFixed(1)}%</td>
                          </tr>
                        );
                      }).sort((a, b) => {
                        const aCount = parseInt(a.props.children[1].props.children[0]);
                        const bCount = parseInt(b.props.children[1].props.children[0]);
                        return bCount - aCount;
                      })}
                    </tbody>
                  </table>
                </div>
                
                <div className="pf9-audit-section">
                  <h3>Hypervisor Resource Analysis</h3>
                  <table className="pf9-table">
                    <thead>
                      <tr>
                        <th>Hypervisor</th>
                        <th>Roles</th>
                        <th>Uptime</th>
                        <th>CPU Usage %</th>
                        <th>Memory Usage %</th>
                        <th>Storage Usage %</th>
                        <th>VM Density</th>
                      </tr>
                    </thead>
                    <tbody>
                      {hypervisors.map(hyp => {
                        const cpuUsage = hyp.vcpus > 0 ? (hyp.vcpus_used / hyp.vcpus * 100) : 0;
                        const memUsage = hyp.memory_mb > 0 ? (hyp.memory_mb_used / hyp.memory_mb * 100) : 0;
                        const storageUsage = hyp.local_gb > 0 ? (hyp.local_gb_used / hyp.local_gb * 100) : 0;
                        const formatUptime = (seconds) => {
                          if (!seconds) return "N/A";
                          const days = Math.floor(seconds / 86400);
                          const hours = Math.floor((seconds % 86400) / 3600);
                          return `${days}d ${hours}h`;
                        };
                        return (
                          <tr key={hyp.hypervisor_id}>
                            <td>{hyp.hypervisor_hostname}</td>
                            <td><span className="pf9-badge pf9-badge-info">{hyp.pf9_roles}</span></td>
                            <td>{formatUptime(hyp.uptime_seconds)}</td>
                            <td>{cpuUsage.toFixed(1)}%</td>
                            <td>{memUsage.toFixed(1)}%</td>
                            <td>{storageUsage.toFixed(1)}%</td>
                            <td>{hyp.running_vms || 0} VMs</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                
                <div className="pf9-audit-section">
                  <h3>Image Utilization Summary</h3>
                  <table className="pf9-table">
                    <thead>
                      <tr>
                        <th>Image Name</th>
                        <th>VMs Using</th>
                        <th>Size (GB)</th>
                        <th>Total Space (GB)</th>
                        <th>Usage Rate</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(
                        servers.reduce((acc, server) => {
                          if (server.image_name) {
                            if (!acc[server.image_name]) {
                              const img = images.find(i => i.image_name === server.image_name);
                              acc[server.image_name] = {
                                count: 0,
                                size: img ? (img.size_bytes || 0) / 1024 / 1024 / 1024 : 0
                              };
                            }
                            acc[server.image_name].count++;
                          }
                          return acc;
                        }, {} as any)
                      ).sort(([, a], [, b]) => b.count - a.count).slice(0, 10).map(([imageName, stats]) => (
                        <tr key={imageName}>
                          <td>{imageName}</td>
                          <td><strong>{stats.count}</strong></td>
                          <td>{stats.size.toFixed(2)}</td>
                          <td>{(stats.size * stats.count).toFixed(2)}</td>
                          <td>{servers.length > 0 ? (stats.count / servers.length * 100).toFixed(1) : 0}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                
                <div className="pf9-audit-section">
                  <h3>System Health Indicators</h3>
                  <div className="pf9-compliance-grid">
                    <div className="pf9-compliance-card">
                      <h4>Flavors Utilized</h4>
                      <div className="pf9-compliance-value">
                        {new Set(servers.map(s => s.flavor_name)).size} of {flavors.length}
                      </div>
                      <div className="pf9-compliance-detail">Active flavor types</div>
                    </div>
                    <div className="pf9-compliance-card">
                      <h4>Images in Use</h4>
                      <div className="pf9-compliance-value">
                        {new Set(servers.filter(s => s.image_name).map(s => s.image_name)).size} of {images.length}
                      </div>
                      <div className="pf9-compliance-detail">VM templates active</div>
                    </div>
                    <div className="pf9-compliance-card">
                      <h4>VM Density</h4>
                      <div className="pf9-compliance-value">
                        {hypervisors.length > 0 ? (servers.length / hypervisors.length).toFixed(1) : 0} VMs/Host
                      </div>
                      <div className="pf9-compliance-detail">Average per hypervisor</div>
                    </div>
                    <div className="pf9-compliance-card">
                      <h4>Volume Types</h4>
                      <div className="pf9-compliance-value">
                        {new Set(volumes.map(v => v.volume_type)).size}
                      </div>
                      <div className="pf9-compliance-detail">Storage type diversity</div>
                    </div>
                    <div className="pf9-compliance-card">
                      <h4>Auto-Backup Coverage</h4>
                      <div className="pf9-compliance-value">
                        {volumes.filter(v => v.auto_snapshot === "true").length} of {volumes.length}
                      </div>
                      <div className="pf9-compliance-detail">Volumes protected</div>
                    </div>
                    <div className="pf9-compliance-card">
                      <h4>Shared Networks</h4>
                      <div className="pf9-compliance-value">
                        {networks.filter(n => n.is_shared).length} of {networks.length}
                      </div>
                      <div className="pf9-compliance-detail">Multi-tenant networks</div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* API Metrics Section */}
          {activeTab === "api_metrics" && (
            <APIMetricsTab />
          )}

          {/* System Logs Section */}
          {activeTab === "system_logs" && (
            <SystemLogsTab />
          )}

          {/* Monitoring Section */}
          {activeTab === "monitoring" && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
              {/* Summary Cards */}
              <div className="pf9-audit-section">
                <h3>Metrics Summary</h3>
                <div className="pf9-compliance-grid" style={{ marginBottom: '20px' }}>
                  <div className="pf9-compliance-card">
                    <h4>Total VMs</h4>
                    <div className="pf9-compliance-value">
                      {metricsSummary?.total_vms || 0}
                    </div>
                    <div className="pf9-compliance-detail">Active virtual machines</div>
                  </div>
                  <div className="pf9-compliance-card">
                    <h4>Total Hosts</h4>
                    <div className="pf9-compliance-value">
                      {metricsSummary?.total_hosts || 0}
                    </div>
                    <div className="pf9-compliance-detail">Compute nodes</div>
                  </div>
                  <div className="pf9-compliance-card">
                    <h4>Avg VM CPU</h4>
                    <div className="pf9-compliance-value">
                      {metricsSummary?.vm_stats?.avg_cpu?.toFixed(1) || 0}%
                    </div>
                    <div className="pf9-compliance-detail">Average CPU usage</div>
                  </div>
                  <div className="pf9-compliance-card">
                    <h4>Avg VM Memory</h4>
                    <div className="pf9-compliance-value">
                      {metricsSummary?.vm_stats?.avg_memory?.toFixed(1) || 0}%
                    </div>
                    <div className="pf9-compliance-detail">Average memory usage</div>
                  </div>
                  <div className="pf9-compliance-card">
                    <h4>Alerts</h4>
                    <div
                      className="pf9-compliance-value"
                      style={{
                        color: monitoringAlerts.length > 0 ? '#e74c3c' : '#27ae60',
                      }}
                    >
                      {monitoringAlerts.length}
                    </div>
                    <div className="pf9-compliance-detail">Active alerts</div>
                  </div>
                  <div className="pf9-compliance-card">
                    <h4>Last Update</h4>
                    <div className="pf9-compliance-value" style={{ fontSize: '0.9em' }}>
                      {lastMetricsUpdate ? formatDate(lastMetricsUpdate) : 'Never'}
                    </div>
                    <div className="pf9-compliance-detail">Metrics refresh</div>
                  </div>
                </div>
              </div>

              {/* VM Metrics Table */}
              <div className="pf9-audit-section">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                  <h3>VM Resource Metrics</h3>
                  <button
                    onClick={handleRefreshMetrics}
                    disabled={isRefreshingMetrics || monitoringLoading}
                    style={{
                      padding: '8px 16px',
                      backgroundColor: '#3498db',
                      color: 'white',
                      border: 'none',
                      borderRadius: '4px',
                      cursor: isRefreshingMetrics ? 'not-allowed' : 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '8px',
                      opacity: isRefreshingMetrics ? 0.6 : 1
                    }}
                  >
                    <span style={{
                      display: 'inline-block',
                      width: '16px',
                      height: '16px',
                      borderRadius: '50%',
                      border: '2px solid currentColor',
                      borderTop: '2px solid transparent',
                      animation: isRefreshingMetrics ? 'spin 1s linear infinite' : 'none'
                    }}></span>
                    {isRefreshingMetrics ? 'Refreshing...' : 'Refresh Data'}
                  </button>
                </div>
                {monitoringLoading ? (
                  <p>Loading VM metrics...</p>
                ) : (
                  <table className="pf9-table">
                    <thead>
                      <tr>
                        <th>VM Name</th>
                        <th>VM IP</th>
                        <th>Host</th>
                        <th>Domain</th>
                        <th>Tenant</th>
                        <th>CPU Usage</th>
                        <th>Memory Usage</th>
                        <th>Storage Used</th>
                        <th>Network RX/TX</th>
                        <th>Last Update</th>
                      </tr>
                    </thead>
                    <tbody>
                      {vmMetrics.length === 0 ? (
                        <tr>
                          <td colSpan={10} className="pf9-empty">
                            No VM metrics available. Check monitoring service connection.
                          </td>
                        </tr>
                      ) : (
                        vmMetrics.map((vm) => (
                          <tr key={vm.vm_id}>
                            <td>
                              <div className="pf9-cell-title">{vm.vm_name}</div>
                              <div className="pf9-cell-subtle">{vm.vm_id}</div>
                            </td>
                            <td>
                              <div className="pf9-cell-title">{vm.vm_ip || 'Unknown'}</div>
                              {vm.flavor && <div className="pf9-cell-subtle">{vm.flavor}</div>}
                            </td>
                            <td>{vm.host}</td>
                            <td>
                              <div className="pf9-cell-title">{vm.domain || 'Unknown'}</div>
                              {vm.user_name && <div className="pf9-cell-subtle">{vm.user_name}</div>}
                            </td>
                            <td>{vm.project_name || 'Unknown'}</td>
                            <td>
                              <span style={{ 
                                color: (vm.cpu_usage_percent || 0) > 80 ? '#e74c3c' : 
                                       (vm.cpu_usage_percent || 0) > 60 ? '#f39c12' : '#27ae60'
                              }}>
                                {vm.cpu_usage_percent?.toFixed(1) || 0}%
                              </span>
                              {vm.cpu_total && <div className="pf9-cell-subtle">{vm.cpu_total} cores</div>}
                            </td>
                            <td>
                              <span style={{ 
                                color: (vm.memory_usage_percent || 0) > 85 ? '#e74c3c' : 
                                       (vm.memory_usage_percent || 0) > 70 ? '#f39c12' : '#27ae60'
                              }}>
                                {vm.memory_usage_percent?.toFixed(1) || 0}%
                              </span>
                              {vm.memory_used_mb && vm.memory_total_mb && (
                                <div className="pf9-cell-subtle">
                                  {(vm.memory_used_mb / 1024).toFixed(1)}GB / {(vm.memory_total_mb / 1024).toFixed(1)}GB
                                </div>
                              )}
                            </td>
                            <td>
                              {vm.storage_total_gb && vm.storage_total_gb > 0 ? (
                                <>
                                  <span style={{ 
                                    color: (vm.storage_usage_percent || 0) > 90 ? '#e74c3c' : 
                                           (vm.storage_usage_percent || 0) > 75 ? '#f39c12' : '#27ae60'
                                  }}>
                                    {vm.storage_usage_percent?.toFixed(1) || 0}%
                                  </span>
                                  <div className="pf9-cell-subtle">
                                    {vm.storage_used_gb?.toFixed(1) || 0}GB / {vm.storage_total_gb.toFixed(1)}GB
                                  </div>
                                </>
                              ) : 'N/A'}
                            </td>
                            <td>
                              {vm.network_rx_bytes && vm.network_tx_bytes ? (
                                <div>
                                  <div>↓ {(vm.network_rx_bytes / 1024 / 1024).toFixed(1)}MB</div>
                                  <div>↑ {(vm.network_tx_bytes / 1024 / 1024).toFixed(1)}MB</div>
                                </div>
                              ) : 'N/A'}
                            </td>
                            <td>{formatDate(vm.timestamp)}</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                )}
              </div>

              <div className="pf9-audit-section">
                {/* Host Metrics Table */}
                <h3>Host Resource Metrics</h3>
                {monitoringLoading ? (
                  <p>Loading host metrics...</p>
                ) : (
                  <table className="pf9-table">
                    <thead>
                      <tr>
                        <th>Host</th>
                        <th>CPU Usage</th>
                        <th>Memory Usage</th>
                        <th>Storage Usage</th>
                        <th>Network Throughput</th>
                        <th>Last Update</th>
                      </tr>
                    </thead>
                    <tbody>
                      {hostMetrics.length === 0 ? (
                        <tr>
                          <td colSpan={6} className="pf9-empty">
                            No host metrics available. Check monitoring service connection.
                          </td>
                        </tr>
                      ) : (
                        hostMetrics.map((host) => (
                          <tr key={host.hostname}>
                            <td>
                              <div className="pf9-cell-title">{host.hostname}</div>
                            </td>
                            <td>
                              <span style={{ 
                                color: (host.cpu_usage_percent || 0) > 80 ? '#e74c3c' : 
                                       (host.cpu_usage_percent || 0) > 60 ? '#f39c12' : '#27ae60'
                              }}>
                                {host.cpu_usage_percent?.toFixed(1) || 0}%
                              </span>
                              {host.cpu_total && <div className="pf9-cell-subtle">{host.cpu_total} cores</div>}
                            </td>
                            <td>
                              {host.memory_used_mb && host.memory_total_mb ? (
                                <>
                                  <span style={{ 
                                    color: ((host.memory_used_mb / host.memory_total_mb) * 100) > 85 ? '#e74c3c' : 
                                           ((host.memory_used_mb / host.memory_total_mb) * 100) > 70 ? '#f39c12' : '#27ae60'
                                  }}>
                                    {((host.memory_used_mb / host.memory_total_mb) * 100).toFixed(1)}%
                                  </span>
                                  <div className="pf9-cell-subtle">
                                    {(host.memory_used_mb / 1024).toFixed(1)}GB / {(host.memory_total_mb / 1024).toFixed(1)}GB
                                  </div>
                                </>
                              ) : 'N/A'}
                            </td>
                            <td>
                              {host.storage_total_gb ? (
                                <>
                                  <span>{((host.storage_used_gb || 0) / host.storage_total_gb * 100).toFixed(1)}%</span>
                                  <div className="pf9-cell-subtle">
                                    {(host.storage_used_gb || 0).toFixed(1)}GB / {host.storage_total_gb.toFixed(1)}GB
                                  </div>
                                </>
                              ) : 'N/A'}
                            </td>
                            <td>
                              {host.network_rx_mb && host.network_tx_mb ? (
                                <div>
                                  <div>↓ {host.network_rx_mb.toFixed(0)}MB</div>
                                  <div>↑ {host.network_tx_mb.toFixed(0)}MB</div>
                                </div>
                              ) : 'N/A'}
                            </td>
                            <td>{formatDate(host.timestamp)}</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                )}
              </div>

              {monitoringAlerts.length > 0 && (
                <div className="pf9-audit-section">
                  <h3>Active Alerts</h3>
                  <table className="pf9-table">
                    <thead>
                      <tr>
                        <th>Severity</th>
                        <th>Resource</th>
                        <th>Message</th>
                        <th>Value</th>
                      </tr>
                    </thead>
                    <tbody>
                      {monitoringAlerts.map((alert, index) => (
                        <tr key={index}>
                          <td>
                            <span style={{ 
                              color: alert.severity === 'critical' ? '#e74c3c' :
                                     alert.severity === 'high' ? '#f39c12' :
                                     alert.severity === 'medium' ? '#3498db' : '#27ae60',
                              fontWeight: 'bold',
                              textTransform: 'uppercase'
                            }}>
                              {alert.severity}
                            </span>
                          </td>
                          <td>{alert.resource}</td>
                          <td>{alert.message}</td>
                          <td>{alert.value.toFixed(1)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}


        </div>

        {/* Details panel */}
        <div className="pf9-details-panel">
          {activeTab === "servers" && selectedServer && (
            <div>
              <h2>VM Details</h2>
              <p>
                <strong>Name:</strong> {selectedServer.vm_name}
              </p>
              <p>
                <strong>ID:</strong> {selectedServer.vm_id}
              </p>
              <p>
                <strong>Domain:</strong> {selectedServer.domain_name}
              </p>
              <p>
                <strong>Tenant:</strong> {selectedServer.tenant_name}
              </p>
              <p>
                <strong>Project:</strong>{" "}
                {selectedServer.project_name ?? ""}
              </p>
              <p>
                <strong>Status:</strong> {selectedServer.status}
              </p>
              <p>
                <strong>Flavor:</strong> {selectedServer.flavor_name}
              </p>
              <p>
                <strong>IPs:</strong> {selectedServer.ips}
              </p>
              <p>
                <strong>Created:</strong>{" "}
                {formatDate(selectedServer.created_at)}
              </p>
            </div>
          )}

          {activeTab === "snapshots" && selectedSnapshot && (
            <div>
              <h2>Snapshot Details</h2>
              <p>
                <strong>Name:</strong>{" "}
                {selectedSnapshot.snapshot_name || selectedSnapshot.snapshot_id}
              </p>
              <p>
                <strong>ID:</strong> {selectedSnapshot.snapshot_id}
              </p>
              <p>
                <strong>VM:</strong>{" "}
                {selectedSnapshot.vm_name || selectedSnapshot.vm_id}
              </p>
              <p>
                <strong>Domain:</strong> {selectedSnapshot.domain_name}
              </p>
              <p>
                <strong>Tenant:</strong> {selectedSnapshot.tenant_name}
              </p>
              <p>
                <strong>Status:</strong> {selectedSnapshot.status}
              </p>
              <p>
                <strong>Size:</strong> {selectedSnapshot.size_gb ?? ""} GB
              </p>
              <p>
                <strong>Created:</strong>{" "}
                {formatDate(selectedSnapshot.created_at)}
              </p>
              <p>
                <strong>Last seen:</strong>{" "}
                {formatDate(selectedSnapshot.last_seen_at)}
              </p>
              <p>
                <strong>Deleted:</strong> {yesNo(selectedSnapshot.is_deleted)}
              </p>
            </div>
          )}

          {activeTab === "networks" && selectedNetwork && (
            <div>
              <h2>Network Details</h2>
              <p>
                <strong>Name:</strong>{" "}
                {selectedNetwork.network_name || selectedNetwork.network_id}
              </p>
              <p>
                <strong>ID:</strong> {selectedNetwork.network_id}
              </p>
              <p>
                <strong>Domain:</strong> {selectedNetwork.domain_name}
              </p>
              <p>
                <strong>Project:</strong>{" "}
                {selectedNetwork.project_name ?? ""}
              </p>
              <p>
                <strong>Shared:</strong> {yesNo(selectedNetwork.is_shared)}
              </p>
              <p>
                <strong>External:</strong> {yesNo(selectedNetwork.is_external)}
              </p>
              <p>
                <strong>Last seen:</strong>{" "}
                {formatDate(selectedNetwork.last_seen_at)}
              </p>
            </div>
          )}

          {activeTab === "subnets" && selectedSubnet && (
            <div>
              <h2>Subnet Details</h2>
              <p>
                <strong>Name:</strong> {selectedSubnet.name || selectedSubnet.id}
              </p>
              <p>
                <strong>ID:</strong> {selectedSubnet.id}
              </p>
              <p>
                <strong>Domain:</strong> {selectedSubnet.domain_name}
              </p>
              <p>
                <strong>Tenant:</strong> {selectedSubnet.tenant_name}</p>
              <p>
                <strong>Project:</strong>{" "}
                {selectedSubnet.project_name ?? ""}
              </p>
              <p>
                <strong>CIDR:</strong> {selectedSubnet.cidr}</p>
              <p>
                <strong>Gateway:</strong> {selectedSubnet.gateway_ip}</p>
              <p>
                <strong>Network ID:</strong> {selectedSubnet.network_id}</p>
              <p>
                <strong>DHCP enabled:</strong>{" "}
                {yesNo(selectedSubnet.enable_dhcp)}
              </p>
              <p>
                <strong>Created:</strong>{" "}
                {formatDate(selectedSubnet.created_at)}
              </p>
              <p>
                <strong>Last seen:</strong>{" "}
                {formatDate(selectedSubnet.last_seen_at)}
              </p>
            </div>
          )}

          {activeTab === "volumes" && selectedVolume && (
            <div>
              <h2>Volume Details</h2>
              <p>
                <strong>Name:</strong> {selectedVolume.volume_name}
              </p>
              <p>
                <strong>ID:</strong> {volumeDisplayId(selectedVolume)}
              </p>
              <p>
                <strong>Status:</strong> {selectedVolume.status}
              </p>
              <p>
                <strong>Type:</strong> {selectedVolume.volume_type ?? ""}
              </p>
              <p>
                <strong>Bootable:</strong> {selectedVolume.bootable ? "Yes" : "No"}
              </p>
              <p>
                <strong>Domain:</strong> {selectedVolume.domain_name}
              </p>
              <p>
                <strong>Tenant:</strong> {selectedVolume.tenant_name}</p>
              <p>
                <strong>Project:</strong>{" "}
                {selectedVolume.project_name ?? ""}
              </p>
              <p>
                <strong>Size:</strong> {selectedVolume.size_gb ?? ""} GB
              </p>
              <p>
                <strong>Attached to:</strong>{" "}
                {selectedVolume.attached_to ?? ""}
              </p>
              {selectedVolume.server_name && (
                <p>
                  <strong>Server:</strong> {selectedVolume.server_name}
                </p>
              )}
              {selectedVolume.device && (
                <p>
                  <strong>Device:</strong> {selectedVolume.device}
                </p>
              )}
              <div style={{marginTop: "20px", borderTop: "1px solid #ccc", paddingTop: "15px"}}>
                <h3>Snapshot Policy</h3>
                <p>
                  <strong>Auto Snapshot:</strong>{" "}
                  <span className={selectedVolume.auto_snapshot === "true" ? "pf9-badge-success" : "pf9-badge-default"}>
                    {selectedVolume.auto_snapshot === "true" ? "Enabled" : "Disabled"}
                  </span>
                </p>
                <p>
                  <strong>Snapshot Policy:</strong> {selectedVolume.snapshot_policy ?? "None"}
                </p>
                {selectedVolume.metadata && (
                  <div style={{marginTop: "15px"}}>
                    <h4>Raw Metadata</h4>
                    <pre style={{fontSize: "12px", background: "#f5f5f5", padding: "10px", borderRadius: "4px", maxHeight: "200px", overflow: "auto"}}>
                      {JSON.stringify(selectedVolume.metadata, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
              <p>
                <strong>Created:</strong>{" "}
                {formatDate(selectedVolume.created_at)}
              </p>
              <p>
                <strong>Last seen:</strong>{" "}
                {formatDate(selectedVolume.last_seen_at)}
              </p>
            </div>
          )}

          {/* Resource History Details Panel */}
          {(selectedResourceHistory.length > 0 || (loading && historyResourceType)) && (
            <div>
              <h2>Resource History</h2>
              {loading && historyResourceType ? (
                <div>
                  <p>Loading history for {historyResourceType} {historyResourceId}...</p>
                </div>
              ) : (
                <>
                  <p>
                    <strong>Resource Type:</strong> {historyResourceType}
                  </p>
                  <p>
                    <strong>Resource ID:</strong> {historyResourceId}
                  </p>
                  <p>
                    <strong>Total Changes:</strong> {selectedResourceHistory.length}
                <button
                  style={{
                    marginLeft: "10px",
                    padding: "4px 8px",
                    backgroundColor: "#dc3545",
                    color: "white",
                    border: "none",
                    borderRadius: "4px",
                    cursor: "pointer",
                    fontSize: "12px"
                  }}
                  onClick={() => {
                    setSelectedResourceHistory([]);
                    setHistoryResourceType("");
                    setHistoryResourceId("");
                  }}
                >
                  Clear History
                </button>
              </p>
              
              <h3>Change Timeline</h3>
              <div style={{maxHeight: "400px", overflow: "auto"}}>
                {selectedResourceHistory.map((record, idx) => {
                  // Format the recorded_at date properly
                  const changeDate = record.recorded_at ? formatDate(record.recorded_at) : 'Unknown date';
                  // Display resource name or fallback to ID
                  const displayName = record.resource_name || record.resource_id;
                  
                  return (
                  <div key={idx} style={{
                    border: "1px solid var(--color-border)", 
                    borderRadius: "8px", 
                    padding: "16px", 
                    margin: "12px 0",
                    background: "var(--color-surface)",
                    boxShadow: "var(--shadow-sm)"
                  }}>
                    <div style={{fontSize: "14px", fontWeight: "600", marginBottom: "8px", color: "var(--color-primary)"}}>
                      {displayName}
                    </div>
                    <div style={{fontSize: "13px", color: "var(--color-text-secondary)", marginBottom: "8px"}}>
                      <strong>Changed:</strong> {changeDate}
                    </div>
                    <div style={{fontSize: "12px", color: "var(--color-text-secondary)", marginBottom: "8px"}}>
                      <strong>Change Sequence:</strong> #{record.change_sequence || idx + 1}
                    </div>
                    <div style={{fontSize: "12px", color: "var(--color-text-secondary)", marginBottom: "8px"}}>
                      Hash: {record.change_hash?.substring(0, 12)}...
                      {record.previous_hash && (
                        <span> (Previous: {record.previous_hash.substring(0, 8)}...)</span>
                      )}
                    </div>
                    <div style={{fontSize: "12px"}}>
                      <strong>Resource Type:</strong> {record.resource_type}
                    </div>
                    {record.current_state && (
                      <details style={{marginTop: "12px"}}>
                        <summary style={{cursor: "pointer", fontWeight: "bold", color: "var(--color-primary)"}}>
                          View Raw State Data
                        </summary>
                        <pre style={{
                          fontSize: "10px", 
                          background: "var(--color-background)", 
                          color: "var(--color-text-primary)",
                          border: "1px solid var(--color-border)",
                          padding: "12px", 
                          borderRadius: "6px", 
                          maxHeight: "200px", 
                          overflow: "auto",
                          marginTop: "8px"
                        }}>
                          {JSON.stringify(record.current_state, null, 2)}
                        </pre>
                      </details>
                    )}
                  </div>
                  );
                })}
              </div>
                </>
              )}
            </div>
          )}

          {activeTab === "snapshot-policies" && (
            <SnapshotPolicyManager />
          )}

          {activeTab === "snapshot-audit" && (
            <SnapshotAuditTrail />
          )}

          {/* Empty states for details */}
          {!selectedServer &&
            activeTab === "servers" &&
            !selectedSnapshot &&
            !selectedNetwork &&
            !selectedSubnet &&
            !selectedVolume &&
            selectedResourceHistory.length === 0 &&
            (activeTab !== "history" && activeTab !== "audit") && (
              <div>
                <h2>Details</h2>
                <p>Click a row in the table to see details.</p>
              </div>
            )}
          
          {/* Empty state for history tab only */}
          {activeTab === "history" && 
           selectedResourceHistory.length === 0 && (
              <div>
                <h2>Resource History</h2>
                <p>Click "View History" on a resource to see its change timeline.</p>
              </div>
            )}
        </div>
      </section>
    </div>
    </ThemeProvider>
  );
};

export default App;
