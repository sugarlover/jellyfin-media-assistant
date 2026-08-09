# Step 34 CI template-test dependency

Step 34 renders selected Home Assistant Jinja templates in its regression tests.
The test suite therefore declares Jinja as a development-only dependency in
`requirements-dev.txt`.

This does not add a runtime dependency to the Home Assistant custom integration.
Home Assistant already provides its own template environment at runtime. The
package is installed only by the repository test workflow and local development
environments that install `requirements-dev.txt`.
