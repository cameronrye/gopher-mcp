"""Additional security tests to improve coverage."""


from gopher_mcp.security import TLSSecurityManager, SecurityLevel, TLSSecurityConfig


class TestTLSSecurityManagerAdditional:
    """Additional tests for TLS security manager."""

    def test_validate_host_with_blocked_hosts(self):
        """Test host validation with blocked hosts."""
        config = TLSSecurityConfig(blocked_hosts={"malicious.com", "bad.example.org"})
        manager = TLSSecurityManager(config)

        # Test blocked host
        assert not manager.validate_host("malicious.com")
        assert not manager.validate_host("bad.example.org")

        # Test allowed host
        assert manager.validate_host("good.example.com")

    def test_validate_host_with_allowed_hosts(self):
        """Test host validation with allowed hosts."""
        config = TLSSecurityConfig(allowed_hosts={"example.com", "trusted.org"})
        manager = TLSSecurityManager(config)

        # Test allowed host
        assert manager.validate_host("example.com")
        assert manager.validate_host("trusted.org")

        # Test non-allowed host
        assert not manager.validate_host("unknown.com")

    def test_validate_host_no_restrictions(self):
        """Test host validation with no restrictions."""
        config = TLSSecurityConfig()
        manager = TLSSecurityManager(config)

        # All hosts should be allowed when no restrictions
        assert manager.validate_host("any.example.com")
        assert manager.validate_host("another.org")

    def test_security_level_enum_values(self):
        """Test SecurityLevel enum values."""
        assert SecurityLevel.LOW.value == "low"
        assert SecurityLevel.MEDIUM.value == "medium"
        assert SecurityLevel.HIGH.value == "high"
        assert SecurityLevel.PARANOID.value == "paranoid"

    def test_tls_security_config_defaults(self):
        """Test TLS security config default values."""
        config = TLSSecurityConfig()

        assert config.security_level == SecurityLevel.MEDIUM
        assert config.require_sni is True
        assert config.require_perfect_forward_secrecy is True
        assert config.allow_legacy_renegotiation is False
        assert config.connection_timeout == 30.0
        assert config.handshake_timeout == 10.0
        assert config.max_cert_chain_length == 10
        assert config.require_cert_transparency is False

    def test_tls_security_config_custom_values(self):
        """Test TLS security config with custom values."""
        config = TLSSecurityConfig(
            security_level=SecurityLevel.HIGH,
            require_sni=False,
            connection_timeout=60.0,
            max_cert_chain_length=5,
        )

        assert config.security_level == SecurityLevel.HIGH
        assert config.require_sni is False
        assert config.connection_timeout == 60.0
        assert config.max_cert_chain_length == 5
