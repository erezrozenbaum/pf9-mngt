# Contributing to Platform9 Management System

Thank you for your interest in contributing to the Platform9 Management System!

## 📋 Table of Contents

1. [Code of Conduct](#code-of-conduct)
2. [Getting Started](#getting-started)
3. [Development Setup](#development-setup)
4. [How to Contribute](#how-to-contribute)
5. [Reporting Bugs](#reporting-bugs)
6. [Suggesting Enhancements](#suggesting-enhancements)
7. [Pull Requests](#pull-requests)
8. [Coding Standards](#coding-standards)
9. [Testing](#testing)

---

## 📜 Code of Conduct

### Our Pledge

We are committed to providing a welcoming and inspiring community for all. Please be respectful to other contributors and maintainers.

### Our Standards

Examples of behavior that contributes to creating a positive environment include:
- Using welcoming and inclusive language
- Being respectful of differing opinions and experiences
- Accepting constructive criticism gracefully
- Focusing on what is best for the community
- Showing empathy towards other community members

---

## 🚀 Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+
- Docker & Docker Compose
- Git

### Local Development Setup

```bash
# Clone the repository
git clone https://github.com/yourusername/pf9-mngt.git
cd pf9-mngt

# Set up Python environment
python -m venv .venv
.venv\Scripts\Activate.ps1  # On Windows
# or
source .venv/bin/activate   # On Linux/Mac

# Install Python dependencies
pip install -r api/requirements.txt
pip install -r monitoring/requirements.txt

# Set up Node.js for frontend
cd pf9-ui
npm install
cd ..

# Configure environment
cp .env.template .env
# Edit .env with your configuration

# Start services
docker-compose up -d
.\startup.ps1  # On Windows
```

---

## 💻 Development Setup

### Project Structure

```
pf9-mngt/
├── api/                    # Backend FastAPI application
├── monitoring/             # Monitoring service
├── pf9-ui/                # Frontend React application
├── db/                    # Database scripts
├── ldap/                  # LDAP configuration
├── docs/                  # Documentation
└── [deployment scripts]   # Setup and maintenance scripts
```

### Useful Commands

```bash
# Run API locally (development)
cd api
uvicorn main:app --reload --port 8000

# Run monitoring service locally
cd monitoring
uvicorn main:app --reload --port 8001

# Run frontend with hot reload
cd pf9-ui
npm run dev

# Run tests (if available)
pytest api/
npm test --workspace=pf9-ui

# Build for production
npm run build --workspace=pf9-ui
docker-compose -f docker-compose.yml build

# Check code quality
pylint api/
npm run lint --workspace=pf9-ui
```

---

## 🤝 How to Contribute

### 1. Fork the Repository

Click the "Fork" button on GitHub to create your own copy.

### 2. Create a Feature Branch

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b bugfix/issue-description
```

Use clear, descriptive branch names:
- `feature/add-user-management`
- `bugfix/fix-cors-issue`
- `docs/update-security-guide`

### 3. Make Your Changes

- Write clear, commented code
- Follow the coding standards (see below)
- Keep changes focused and atomic
- Update documentation as needed

### 4. Test Your Changes

- Test locally before committing
- Add tests for new features
- Verify all tests pass
- Test with different roles (viewer, operator, admin, superadmin)

### 5. Commit with Clear Messages

```bash
git commit -m "Add feature: brief description

- More detailed explanation
- What problem it solves
- Any relevant issue numbers (#123)
"
```

### 6. Push and Create Pull Request

```bash
git push origin feature/your-feature-name
```

Then create a Pull Request on GitHub with:
- Clear title
- Description of changes
- Why this change is needed
- References to related issues
- Screenshots (if UI changes)

---

## 🐛 Reporting Bugs

### Before Submitting

- Check if the bug already exists in Issues
- Verify you're using the latest version
- Check the documentation and FAQ

### Submitting a Bug Report

Please include:
- **Clear title**: What's the bug?
- **Description**: What did you expect? What actually happened?
- **Steps to reproduce**:
  1. Did this...
  2. Then did that...
  3. Bug occurred when...
- **Environment**:
  - OS (Windows/Linux/Mac)
  - Python version
  - Docker version
  - Browser (if UI issue)
- **Logs**: Relevant error messages or logs
- **Screenshots**: If applicable

### Example Bug Report

```
Title: CORS policy blocks requests from production domain

Description:
When accessing the API from https://pf9-mgmt.company.com, all requests fail with CORS error.

Steps to Reproduce:
1. Deploy to production domain
2. Access UI from https://pf9-mgmt.company.com
3. Try to load servers list

Expected: Servers list loads successfully
Actual: CORS error in browser console

Environment:
- OS: Ubuntu 20.04
- Python: 3.11.4
- Docker: 24.0.1
- Browser: Chrome 120

Error:
Access to XMLHttpRequest at 'http://localhost:8000/servers' from origin 'https://pf9-mgmt.company.com' 
has been blocked by CORS policy
```

---

## 💡 Suggesting Enhancements

### Before Submitting

- Check if the feature already exists
- Check if it's already suggested in Issues
- Consider if it aligns with project goals

### Submitting an Enhancement

Include:
- **Clear title**: What feature?
- **Description**: What problem does it solve?
- **Use case**: How would you use it?
- **Examples**: Show how it might work
- **Alternative solutions**: Any other approaches?

### Example Feature Request

```
Title: Add email notifications for failed snapshots

Description:
Currently, failed snapshots are only logged. It would be helpful to receive email notifications.

Use Case:
When a snapshot fails due to capacity or quota issues, we want to know immediately 
to take corrective action.

Proposed Solution:
Add SMTP configuration in .env and send emails when:
- Snapshot creation fails
- Retention cleanup fails
- Policy assignment fails

Alternative Solutions:
- Webhook integration to external systems
- Slack/Teams integration
```

---

## 🔄 Pull Requests

### Checklist Before Submitting

- [ ] Branch is up to date with main
- [ ] Code follows style guidelines
- [ ] Tests pass locally
- [ ] Documentation is updated
- [ ] No hardcoded secrets/credentials
- [ ] Commit messages are clear
- [ ] Changes are focused and atomic

### PR Title Format

```
[TYPE] Description

Types: Feature, Bugfix, Docs, Security, Performance, Refactor
Example: [Feature] Add role-based API endpoint filtering
```

### PR Description Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Related Issue
Closes #123

## Testing Done
- Tested with Python 3.11
- Tested with PostgreSQL 16
- Tested RBAC enforcement
- Manual testing on Windows 11

## Screenshots (if applicable)
[Add screenshots for UI changes]

## Checklist
- [ ] Code follows style guidelines
- [ ] Self-review completed
- [ ] Comments added for complex logic
- [ ] Documentation updated
- [ ] No new warnings generated
- [ ] Tests added/updated
```

---

## 🎨 Coding Standards

### Python (Backend & Scripts)

```python
# Follow PEP 8
# 4 spaces for indentation
# Max 100 characters per line
# Use type hints where possible

def authenticate_user(username: str, password: str) -> Optional[Dict]:
    """
    Authenticate user against LDAP server.
    
    Args:
        username: User's login name
        password: User's password
        
    Returns:
        User info dict if successful, None otherwise
        
    Raises:
        LDAPException: If LDAP server is unavailable
    """
    # Implementation here
    pass
```

### TypeScript/React (Frontend)

```typescript
// Use 2 spaces for indentation
// Use descriptive variable names
// Add comments for complex logic

interface UserRole {
  username: string;
  role: 'viewer' | 'operator' | 'admin' | 'superadmin';
  isActive: boolean;
}

const RoleFilter: React.FC<{ role: UserRole }> = ({ role }) => {
  // Implementation here
  return <div>{role.username}</div>;
};
```

### Documentation

- Use clear, concise language
- Include code examples
- Update README for significant changes
- Keep CHANGELOG.md updated (if used)

---

## 🧪 Testing

### Python Testing

```bash
# Install pytest
pip install pytest pytest-cov

# Run tests
pytest api/

# Run with coverage
pytest --cov=api api/

# Run specific test
pytest api/test_auth.py::test_login_success
```

### Frontend Testing

```bash
# Run tests
npm test --workspace=pf9-ui

# Test with coverage
npm test -- --coverage --workspace=pf9-ui

# Run specific test
npm test -- UserManagement.test.tsx --workspace=pf9-ui
```

### Manual Testing Scenarios

**For Authentication:**
- [ ] Login with viewer role
- [ ] Login with admin role
- [ ] Test failed login attempts (3+ tries)
- [ ] Test token expiration
- [ ] Test logout functionality

**For API Endpoints:**
- [ ] GET requests return correct data
- [ ] POST requests require authentication
- [ ] Permission checks work (403 Forbidden)
- [ ] Invalid input is rejected
- [ ] Database changes are persisted

**For UI:**
- [ ] Responsive design (desktop, tablet)
- [ ] Theme toggle works
- [ ] Role-based tab visibility
- [ ] Admin operations restricted to admin role
- [ ] Forms validation works

---

## 📚 Documentation Standards

When contributing documentation:

1. **README updates** - Major features or setup changes
2. **Code comments** - Complex logic and business rules
3. **Docstrings** - All functions and classes
4. **DOCS/** - Comprehensive guides
5. **Inline comments** - Only when necessary

Example documentation:

```python
def get_servers_with_filtering(
    domain: str,
    project: str,
    sort_by: str = 'name'
) -> List[Server]:
    """
    Retrieve servers with optional filtering.
    
    Args:
        domain: Filter by domain name
        project: Filter by project name
        sort_by: Sort key ('name', 'status', 'created_at')
        
    Returns:
        List of Server objects matching filters
        
    Raises:
        ValueError: If sort_by is not a valid field
        PermissionError: If user lacks read permission
        
    Example:
        >>> servers = get_servers_with_filtering('default', 'admin')
        >>> for server in servers:
        ...     print(server.name, server.status)
    """
```

---

## 🔒 Security Considerations

When contributing:

1. **Never commit secrets** - Use environment variables
2. **Validate all inputs** - Prevent injection attacks
3. **Check permissions** - Ensure RBAC is enforced
4. **Use parameterized queries** - Prevent SQL injection
5. **Log sensitive events** - But not credentials
6. **Review security docs** - See docs/SECURITY.md

---

## 📞 Getting Help

- **Documentation**: Check [docs/](docs/) folder
- **Issues**: Search existing issues on GitHub
- **Discussions**: Use GitHub Discussions for questions
- **Documentation issues**: Use the "documentation" label

---

## 📄 License

By contributing, you agree that your contributions will be licensed under the MIT License.

---

## 🙏 Thank You!

We appreciate your contributions to making Platform9 Management System better for everyone!

---

**Last Updated**: February 4, 2026  
**Maintained by**: Project Contributors
