# Platform9 Management UI

Modern React-based frontend for the Platform9 Management System, providing comprehensive infrastructure management with role-based access control and real-time monitoring.

## 🎯 Overview

### What is Platform9?

Platform9 is a cloud infrastructure management platform that simplifies operating private and hybrid clouds. It brings together compute, storage, and networking management behind a unified, secure control plane and makes it easier for teams to manage virtualization and container environments.

### Why this project exists

This project does **not** replace the official Platform9 UI. It provides an engineering-focused, role-aware inventory and maintenance UI that complements Platform9 by improving day-to-day operational visibility. The goal is faster navigation, clearer context, and human-friendly naming (project/tenant/host names) instead of only UUID-based views.

It also delivers a wider view of the overall system and adds functionality such as snapshot management, volume management, and other operational tools that extend the current Platform9 UI. This creates an added-value engineering console to assist teams in managing Platform9 environments.

### Key benefits

- **Unified operations**: Manage infrastructure, platform resources, and users from a single console.
- **Built-in governance**: Role-based access control and audit history help enforce policies.
- **Operational speed**: Real-time monitoring and quick filtering reduce time-to-diagnosis.
- **Lower complexity**: Consistent workflows reduce manual steps and errors.

### What runs under the hood

Platform9 environments are commonly backed by **OpenStack** services. That means the UI must translate OpenStack’s distributed resources (Nova, Cinder, Neutron, Keystone) into a cohesive, operator-friendly view while keeping identity, tenancy, and RBAC boundaries intact.

### Metadata and day‑to‑day operations challenges

OpenStack resources are highly dynamic and spread across multiple services. Capturing, storing, and presenting metadata at scale is hard because:

- **Identifiers are fragmented**: Projects, domains, and resources use different IDs across services.
- **State changes are frequent**: VMs, volumes, and networks change status quickly and asynchronously.
- **Auditability matters**: Operators need a reliable history of changes and ownership.
- **Tasks are cross‑cutting**: Daily workflows (provision, attach, snapshot, resize, troubleshoot) touch multiple services.

This UI focuses on day‑to‑day tasks by normalizing metadata into a single inventory view, then layering on role-aware actions and audit trails.

### Inventory + monitoring system logic

The enhanced inventory and monitoring experience is built on a few principles:

- **Unify resource models**: Normalize OpenStack objects into consistent entities (servers, volumes, networks, projects) with stable identifiers.
- **Join metadata with live metrics**: Merge configuration data with monitoring snapshots to show health and utilization in context.
- **Cache for speed, refresh for accuracy**: Use cached snapshots for fast UI rendering, then refresh incrementally for near real-time status.
- **Role-aware visibility**: Filter and display resources based on RBAC and tenant boundaries.
- **Operational signals first**: Highlight state, alerts, and recent changes so operators can act quickly.

This is the **frontend UI component** of the Platform9 Management System, built with:
- **React 19.2+** - Modern React with hooks and context
- **TypeScript** - Type-safe development
- **Vite** - Fast build tool with HMR (Hot Module Replacement)
- **ESLint** - Code quality and consistency

## 🌟 Features

### 14 Management Tabs
- **Infrastructure**: Servers, Volumes, Snapshots, Networks, Subnets, Ports, Floating IPs
- **Platform**: Domains, Projects, Flavors, Images, Hypervisors
- **Management**: Users (with roles), History, Audit, Monitoring
- **Admin Panel**: User management, roles, permissions, system audit (admin/superadmin only)

### Role-Based UI
- **Dynamic Tab Visibility**: Admin tab only visible to admin/superadmin users
- **Permission-Based Actions**: UI adapts based on user role
- **Authentication Integration**: JWT token-based authentication with LDAP backend
- **User Context**: Current user info and role displayed in navigation

### Modern UX Features
- **Theme Support**: Light/dark mode toggle with persistent preferences
- **Real-Time Updates**: Auto-refresh capabilities for monitoring
- **Advanced Filtering**: Multi-field filtering and sorting across all tabs
- **Responsive Design**: Works on desktop and tablet devices
- **Type-Safe**: Full TypeScript coverage for reliability

## 🚀 Development Setup

### Prerequisites
- **Node.js 18+** and npm
- **Running Backend API** at http://localhost:8000
- **Running Monitoring Service** at http://localhost:8001

### Installation

```bash
# Navigate to UI directory
cd pf9-ui

# Install dependencies
npm install

# Start development server
npm run dev

# Access UI at http://localhost:5173
```

### Development Commands

```bash
# Start dev server with hot reload
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview

# Lint code
npm run lint

# Type check
npx tsc --noEmit
```

## 📁 Project Structure

```
pf9-ui/
├── src/
│   ├── App.tsx                 # Main application component
│   ├── App.css                 # Global styles
│   ├── main.tsx                # Application entry point
│   ├── index.css               # Base CSS
│   ├── components/
│   │   ├── ThemeToggle.tsx     # Light/dark mode switcher
│   │   └── UserManagement.tsx  # Admin panel component
│   ├── hooks/
│   │   └── useTheme.tsx        # Theme management hook
│   └── assets/                 # Static assets
├── public/                     # Public static files
├── index.html                  # HTML entry point
├── package.json                # Dependencies
├── tsconfig.json               # TypeScript config
├── tsconfig.app.json           # App-specific TS config
├── tsconfig.node.json          # Node-specific TS config
├── vite.config.ts              # Vite configuration
└── eslint.config.js            # ESLint rules
```

## 🔧 Configuration

### Environment Variables

Create `.env` in `pf9-ui/` directory (optional):

```bash
# API endpoints (defaults shown)
VITE_API_URL=http://localhost:8000
VITE_MONITORING_URL=http://localhost:8001
```

### Vite Configuration

The `vite.config.ts` is pre-configured for React development with:
- React plugin with Fast Refresh
- Development server on port 5173
- Hot Module Replacement (HMR)
- TypeScript support

## 🎨 Styling

The UI uses **vanilla CSS** with:
- CSS custom properties for theming
- Light/dark mode support
- Responsive design patterns
- Modern CSS features (Grid, Flexbox)

### Theme System

Theme preferences are stored in localStorage:

```typescript
// src/hooks/useTheme.tsx
const { theme, toggleTheme } = useTheme();

// Theme values: 'light' | 'dark'
// Persists across sessions
```

## 🔐 Authentication Integration

### Login Flow

1. User submits credentials on login page
2. UI sends POST to `/auth/login`
3. Backend validates against LDAP
4. JWT token returned and stored in localStorage
5. Token included in Authorization header for all API requests
6. UI adapts based on user role (viewer/operator/admin/superadmin)

### Token Management

```typescript
// Store token
localStorage.setItem('token', accessToken);

// Include in requests
const headers = {
  'Authorization': `Bearer ${localStorage.getItem('token')}`,
  'Content-Type': 'application/json'
};

// Clear on logout
localStorage.removeItem('token');
```

### Role-Based Rendering

```tsx
// Admin tab conditional rendering
{authUser && (authUser.role === 'admin' || authUser.role === 'superadmin') && (
  <button onClick={() => setActiveTab("admin")}>Admin</button>
)}

// Within Admin panel
.filter(tab => !tab.adminOnly || (user && (user.role === 'admin' || user.role === 'superadmin')))
```

## 📊 API Integration

### Backend Endpoints

The UI communicates with two services:

**Main API** (Port 8000):
- `/auth/login` - User authentication
- `/auth/logout` - Logout and session cleanup
- `/servers` - VM management
- `/volumes` - Volume management
- `/networks` - Network management
- `/admin/*` - Administrative operations
- 40+ total endpoints

**Monitoring Service** (Port 8001):
- `/metrics` - Real-time host and VM metrics
- `/metrics/latest` - Most recent metrics snapshot

### Request Pattern

```typescript
// Example API call with authentication
const fetchServers = async () => {
  const response = await fetch('http://localhost:8000/servers', {
    headers: {
      'Authorization': `Bearer ${localStorage.getItem('token')}`
    }
  });
  
  if (response.status === 403) {
    // Permission denied - show error
  }
  
  const data = await response.json();
  return data;
};
```

## 🧪 Testing

### Manual Testing Checklist

- [ ] Login with viewer role - should not see Admin tab
- [ ] Login with admin role - should see Admin tab with all panels
- [ ] Test logout - token cleared, redirected to login
- [ ] Theme toggle - preference persists across reload
- [ ] Each tab loads data correctly
- [ ] Filtering and sorting work on all tabs
- [ ] Admin operations require admin/superadmin role
- [ ] Permission denied (403) shows appropriate error

## 🏗️ Build & Deployment

### Production Build

```bash
# Build for production
npm run build

# Output: dist/ directory
# - Minified JS and CSS
# - Optimized assets
# - Ready for static hosting
```

### Docker Deployment

The UI is containerized with the main application:

```dockerfile
# pf9-ui/Dockerfile
FROM node:18-alpine as build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
```

## 🔍 Troubleshooting

### Common Issues

**UI shows "Failed to fetch"**
- Ensure backend API is running on port 8000
- Check CORS configuration in backend

**Login fails with valid credentials**
- Check LDAP server is running (port 389)
- Verify user exists in LDAP directory
- Check backend logs for auth errors

**Theme doesn't persist**
- Check browser localStorage is enabled
- Clear localStorage and retry

**403 Forbidden on API calls**
- Token may be expired (8 hour expiration)
- User role may lack required permissions
- Re-login to get fresh token

### Debug Mode

```bash
# Start with verbose logging
npm run dev -- --debug

# Check Vite dev server output
# Browser console for client-side errors
```

## 🛠️ Development Tips

### TypeScript Best Practices
- Always define types for API responses
- Use interfaces for component props
- Enable strict mode in tsconfig.json
- Avoid `any` type - use `unknown` if needed

### React Best Practices
- Use functional components with hooks
- Memoize expensive computations
- Use proper dependency arrays in useEffect
- Avoid inline function definitions in render

### Performance Optimization
- Use React.memo for expensive components
- Implement virtual scrolling for large lists
- Lazy load heavy components
- Optimize image assets

## 📦 Dependencies

### Production Dependencies
- `react` ^19.0.0 - UI framework
- `react-dom` ^19.0.0 - React DOM rendering

### Development Dependencies
- `@vitejs/plugin-react` - Vite React plugin
- `typescript` - Type checking
- `eslint` - Code linting
- `@types/react` - React TypeScript definitions
- `@types/react-dom` - React DOM TypeScript definitions

## 🤝 Contributing

When adding new features:
1. Follow existing code structure
2. Add TypeScript types for all new code
3. Test with different user roles
4. Update this README if adding major features
5. Ensure ESLint passes (`npm run lint`)

## 📄 License

Part of the Platform9 Management System project.

## 🔗 Related Documentation

- [Main README](../README.md) - Project overview
- [Admin Guide](../docs/ADMIN_GUIDE.md) - System administration
- [API Documentation](http://localhost:8000/docs) - Backend API reference
- [Security Guide](../docs/SECURITY.md) - Security features and configuration

---

**Development Server**: http://localhost:5173  
**API Backend**: http://localhost:8000  
**Monitoring API**: http://localhost:8001
