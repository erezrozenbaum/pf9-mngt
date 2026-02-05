"""
Configuration validation for PF9 Management API
Validates all required environment variables on startup
"""
import os
import sys
from typing import Dict, List, Tuple

class ConfigValidator:
    """Validates environment configuration on startup"""
    
    # Required environment variables with descriptions
    REQUIRED_VARS = {
        "PF9_DB_HOST": "PostgreSQL database host",
        "PF9_DB_PORT": "PostgreSQL database port",
        "PF9_DB_NAME": "PostgreSQL database name",
        "PF9_DB_USER": "PostgreSQL database user",
        "PF9_DB_PASSWORD": "PostgreSQL database password",
        "PF9_AUTH_URL": "Platform9 authentication URL",
        "PF9_USERNAME": "Platform9 API username",
        "PF9_PASSWORD": "Platform9 API password",
        "LDAP_SERVER": "LDAP server hostname",
        "LDAP_PORT": "LDAP server port",
        "LDAP_BASE_DN": "LDAP base DN",
        "JWT_SECRET_KEY": "JWT signing secret key",
    }
    
    # Optional with defaults
    OPTIONAL_VARS = {
        "PF9_USER_DOMAIN": ("Default", "OpenStack user domain"),
        "PF9_PROJECT_NAME": ("service", "OpenStack project name"),
        "PF9_PROJECT_DOMAIN": ("Default", "OpenStack project domain"),
        "PF9_REGION_NAME": ("region-one", "OpenStack region name"),
        "JWT_ALGORITHM": ("HS256", "JWT signing algorithm"),
        "JWT_ACCESS_TOKEN_EXPIRE_MINUTES": ("480", "JWT token expiration (minutes)"),
        "ENABLE_AUTHENTICATION": ("true", "Enable authentication"),
        "DEFAULT_ADMIN_USER": ("admin", "Default admin username"),
    }
    
    @classmethod
    def validate(cls) -> Tuple[bool, List[str], List[str]]:
        """
        Validate configuration
        Returns: (is_valid, errors, warnings)
        """
        errors = []
        warnings = []
        
        # Check required variables
        for var, description in cls.REQUIRED_VARS.items():
            value = os.getenv(var)
            if not value or value.strip() == "":
                errors.append(f"Missing required env var: {var} ({description})")
        
        # Check optional variables and apply defaults
        for var, (default, description) in cls.OPTIONAL_VARS.items():
            value = os.getenv(var)
            if not value or value.strip() == "":
                warnings.append(f"Using default for {var}={default} ({description})")
        
        # Validate specific values
        errors.extend(cls._validate_values())
        
        is_valid = len(errors) == 0
        return is_valid, errors, warnings
    
    @classmethod
    def _validate_values(cls) -> List[str]:
        """Validate specific configuration values"""
        errors = []
        
        # Validate JWT secret length
        jwt_secret = os.getenv("JWT_SECRET_KEY", "")
        if jwt_secret and len(jwt_secret) < 32:
            errors.append("JWT_SECRET_KEY should be at least 32 characters for security")
        
        # Validate ports
        db_port = os.getenv("PF9_DB_PORT", "5432")
        ldap_port = os.getenv("LDAP_PORT", "389")
        try:
            if not (1 <= int(db_port) <= 65535):
                errors.append(f"Invalid PF9_DB_PORT: {db_port}")
        except ValueError:
            errors.append(f"PF9_DB_PORT must be a number: {db_port}")
        
        try:
            if not (1 <= int(ldap_port) <= 65535):
                errors.append(f"Invalid LDAP_PORT: {ldap_port}")
        except ValueError:
            errors.append(f"LDAP_PORT must be a number: {ldap_port}")
        
        # Validate JWT token expiration
        token_expire = os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "480")
        try:
            expire_mins = int(token_expire)
            if expire_mins < 1:
                errors.append("JWT_ACCESS_TOKEN_EXPIRE_MINUTES must be positive")
            elif expire_mins > 10080:  # 1 week
                errors.append("JWT_ACCESS_TOKEN_EXPIRE_MINUTES > 1 week is not recommended")
        except ValueError:
            errors.append(f"JWT_ACCESS_TOKEN_EXPIRE_MINUTES must be a number: {token_expire}")
        
        # Validate URLs
        auth_url = os.getenv("PF9_AUTH_URL", "")
        if auth_url and not (auth_url.startswith("http://") or auth_url.startswith("https://")):
            errors.append("PF9_AUTH_URL must start with http:// or https://")
        
        return errors
    
    @classmethod
    def print_validation_results(cls, is_valid: bool, errors: List[str], warnings: List[str]):
        """Print validation results with colors"""
        print("\n" + "="*70)
        print("Configuration Validation Results")
        print("="*70)
        
        if warnings:
            print("\n⚠️  WARNINGS:")
            for warning in warnings:
                print(f"  - {warning}")
        
        if errors:
            print("\n❌ ERRORS:")
            for error in errors:
                print(f"  - {error}")
            print("\n" + "="*70)
            print("❌ Configuration validation FAILED")
            print("="*70 + "\n")
        else:
            print("\n✅ Configuration validation PASSED")
            print("="*70 + "\n")
        
        return is_valid
    
    @classmethod
    def validate_and_exit_on_error(cls):
        """Validate configuration and exit if errors found"""
        is_valid, errors, warnings = cls.validate()
        cls.print_validation_results(is_valid, errors, warnings)
        
        if not is_valid:
            print("Fix configuration errors before starting the service.", file=sys.stderr)
            sys.exit(1)
