# Changelog

## [Unreleased]
### Added
- Added `HowToConfigure` output.

### Changed
- If the `EnvironmentSystemsManagerParametersPath` parameter is not set, use `/${AWS::StackName}` as the default value.

### Removed
- Removed the `EnvironmentSecretARN` and `EnvironmentSecretVersionID` parameters.

## [0.1.0] - 2024-01-14
### Added
- Script to generate CloudFormation templates.
