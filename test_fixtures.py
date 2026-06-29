# test_fixtures.py
# Shared test constants — RFC 5737 documentation addresses (TEST-NET-2).
# Not routable on the public internet; safe for unit tests.

TEST_STATIC_IP   = "198.51.100.10"
TEST_SUBNET      = "255.255.255.0"
TEST_GATEWAY     = "198.51.100.1"
TEST_DNS         = "198.51.100.53"
TEST_IFCONFIG    = (TEST_STATIC_IP, TEST_SUBNET, TEST_GATEWAY, TEST_DNS)
TEST_CLIENT_ADDR = "198.51.100.99"
