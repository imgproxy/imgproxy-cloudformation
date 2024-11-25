# Changelog

## [Unreleased]
### Changed
- Updated the EC2 image ID to the latest Bottlerocket variant.
- Added C8g instances to the `ClusterInstanceType` parameter values.
- Changed CloudFront HTTP version to HTTP2/3.

### Fixed
- Added `should-wait = true` to the EC2 instance configuration so it doesn't register itself in the ECS cluster while in warm pool.
- Fixed WarmPool usage in the EC2 Auto Scaling Group.

## [0.2.1] - 2024-02-28
### Fixed
- Fixed CloudFront Origin Shield region selection.

## [0.2.0] - 2024-02-23
### Added
- Added `HowToConfigure` output.

### Changed
- If the `EnvironmentSystemsManagerParametersPath` parameter is not set, use `/${AWS::StackName}` as the default value.

### Fixed
- Fix stack deletion.

### Removed
- Removed the `EnvironmentSecretARN` and `EnvironmentSecretVersionID` parameters.

## [0.1.0] - 2024-01-14
### Added
- Script to generate CloudFormation templates.
