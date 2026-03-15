# pf9-mngt test suite
#
# Run health + unit tests (no live stack needed):
#   pip install pytest requests
#   pytest tests/ -v -k "not skipif"
#
# Run all tests including live integration:
#   TEST_API_URL=http://localhost:8000 \
#   TEST_ADMIN_EMAIL=admin \
#   TEST_ADMIN_PASSWORD=<password> \
#   pytest tests/ -v
