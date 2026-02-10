#!/usr/bin/env python3
"""
GIDE Search RO-Crate Profile Validator

A utility for validating JSON-LD RO-Crate files against the GIDE search input profile.
This validator performs both JSON Schema validation and semantic validation of the
profile requirements.

Usage:
    python validate_gide_rocrate.py <path_to_rocrate.json>
    python validate_gide_rocrate.py --help
"""

import json
import sys
import argparse
from pathlib import Path
from typing import Any
from dataclasses import dataclass, field

try:
    import jsonschema
    from jsonschema import Draft7Validator, ValidationError
except ImportError:
    print("Error: jsonschema package is required. Install with: pip install jsonschema")
    sys.exit(1)


@dataclass
class ValidationResult:
    """Container for validation results."""

    valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)

    def add_error(self, message: str) -> None:
        self.errors.append(message)
        self.valid = False

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)

    def add_info(self, message: str) -> None:
        self.info.append(message)

    def merge(self, other: "ValidationResult") -> None:
        if not other.valid:
            self.valid = False
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        self.info.extend(other.info)


class GIDEProfileValidator:
    """Validator for GIDE Search RO-Crate profile."""

    SCHEMA_PATH = Path(__file__).parent / "gide-search-profile-schema.json"

    # Required RO-Crate version for detached crates
    MIN_ROCRATE_VERSION = "1.2"

    # Expected types for various entities
    REQUIRED_TYPES = {
        "metadata_descriptor": "CreativeWork",
        "dataset": "Dataset",
        "person": "Person",
        "organisation": ["Organization", "Organisation"],
        "taxon": "Taxon",
        "biosample": "BioSample",
        "defined_term": "DefinedTerm",
        "lab_protocol": "LabProtocol",
        "grant": "Grant",
        "scholarly_article": "ScholarlyArticle",
        "quantitative_value": "QuantitativeValue",
    }

    def __init__(self, schema_path: Path | None = None):
        self.schema_path = schema_path or self.SCHEMA_PATH
        self.schema = self._load_schema()

    def _load_schema(self) -> dict:
        """Load the JSON schema."""
        try:
            with open(self.schema_path) as f:
                return json.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"Schema file not found: {self.schema_path}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in schema file: {e}")

    def validate(self, rocrate_path: str | Path) -> ValidationResult:
        """
        Validate an RO-Crate file against the GIDE profile.

        Args:
            rocrate_path: Path to the RO-Crate metadata descriptor file

        Returns:
            ValidationResult with errors, warnings, and info messages
        """
        result = ValidationResult()

        # Load the RO-Crate
        try:
            with open(rocrate_path) as f:
                data = json.load(f)
        except FileNotFoundError:
            result.add_error(f"File not found: {rocrate_path}")
            return result
        except json.JSONDecodeError as e:
            result.add_error(f"Invalid JSON: {e}")
            return result

        # Run all validations
        result.merge(self._validate_schema(data))
        result.merge(self._validate_context(data))
        result.merge(self._validate_structure(data))
        result.merge(self._validate_semantic_requirements(data))

        return result

    def validate_dict(self, data: dict) -> ValidationResult:
        """
        Validate an RO-Crate dictionary against the GIDE profile.

        Args:
            data: Dictionary containing the RO-Crate data

        Returns:
            ValidationResult with errors, warnings, and info messages
        """
        result = ValidationResult()
        result.merge(self._validate_schema(data))
        result.merge(self._validate_context(data))
        result.merge(self._validate_structure(data))
        result.merge(self._validate_semantic_requirements(data))
        return result

    def _validate_schema(self, data: dict) -> ValidationResult:
        """Validate against the JSON Schema."""
        result = ValidationResult()

        validator = Draft7Validator(self.schema)
        errors = list(validator.iter_errors(data))

        for error in errors:
            path = (
                " -> ".join(str(p) for p in error.absolute_path)
                if error.absolute_path
                else "root"
            )
            result.add_error(f"Schema error at {path}: {error.message}")

        if not errors:
            result.add_info("JSON Schema validation passed")

        return result

    def _validate_context(self, data: dict) -> ValidationResult:
        """Validate the @context includes RO-Crate 1.2+."""
        result = ValidationResult()

        context = data.get("@context")
        if not context:
            result.add_error("Missing @context")
            return result

        # Check for RO-Crate context
        rocrate_context_found = False
        rocrate_version = None

        contexts = context if isinstance(context, list) else [context]

        for ctx in contexts:
            if isinstance(ctx, str) and "w3id.org/ro/crate" in ctx:
                rocrate_context_found = True
                # Extract version number
                import re

                match = re.search(r"/(\d+\.\d+)/", ctx)
                if match:
                    rocrate_version = match.group(1)
                break

        if not rocrate_context_found:
            result.add_error(
                "@context must include RO-Crate context (https://w3id.org/ro/crate/X.X/context)"
            )
        elif rocrate_version:
            try:
                if float(rocrate_version) < float(self.MIN_ROCRATE_VERSION):
                    result.add_error(
                        f"RO-Crate version must be >= {self.MIN_ROCRATE_VERSION} for detached crates (found {rocrate_version})"
                    )
                else:
                    result.add_info(f"RO-Crate version {rocrate_version} detected")
            except ValueError:
                result.add_warning(
                    f"Could not parse RO-Crate version: {rocrate_version}"
                )

        return result

    def _validate_structure(self, data: dict) -> ValidationResult:
        """Validate the required graph structure."""
        result = ValidationResult()

        graph = data.get("@graph", [])
        if not graph:
            result.add_error("@graph is missing or empty")
            return result

        # Build entity index
        entities = {entity.get("@id"): entity for entity in graph if "@id" in entity}

        # Find metadata descriptor
        metadata_descriptor = self._find_metadata_descriptor(entities)
        if not metadata_descriptor:
            result.add_error(
                "Missing RO-Crate Metadata Descriptor (CreativeWork with 'about')"
            )
            return result

        if not self._has_type(metadata_descriptor, "CreativeWork"):
            result.add_error("Metadata descriptor must have @type 'CreativeWork'")

        # Check conformsTo
        conforms_to = metadata_descriptor.get("conformsTo")
        if not conforms_to:
            result.add_error("Metadata descriptor missing 'conformsTo' property")

        # Find root dataset
        about = metadata_descriptor.get("about")
        if not about:
            result.add_error(
                "Metadata descriptor missing 'about' property linking to root dataset"
            )
            return result

        root_id = about.get("@id") if isinstance(about, dict) else about
        if not root_id:
            result.add_error("Root dataset @id is missing or empty")
            return result

        root_dataset = entities.get(root_id)

        if not root_dataset:
            result.add_error(f"Root dataset with @id '{root_id}' not found in graph")
            return result

        if not self._has_type(root_dataset, "Dataset"):
            result.add_error("Root dataset must have @type 'Dataset'")

        # Check root dataset @id is absolute URL
        if not str(root_id).startswith(("http://", "https://")):
            result.add_error(
                f"Root dataset @id must be an absolute URL (found: {root_id})"
            )

        result.add_info(f"Found root dataset: {root_id}")

        return result

    def _validate_semantic_requirements(self, data: dict) -> ValidationResult:
        """Validate semantic requirements from the profile."""
        result = ValidationResult()

        graph = data.get("@graph", [])
        entities = {entity.get("@id"): entity for entity in graph if "@id" in entity}

        # Get root dataset
        metadata_descriptor = self._find_metadata_descriptor(entities)
        if not metadata_descriptor:
            return result  # Already reported in structure validation

        about = metadata_descriptor.get("about")
        root_id = about.get("@id") if isinstance(about, dict) else about
        root_dataset = entities.get(root_id)

        if not root_dataset:
            return result  # Already reported

        # Validate required entities
        result.merge(self._validate_taxons(root_dataset, entities))
        result.merge(self._validate_imaging_methods(root_dataset, entities))
        result.merge(self._validate_authors(root_dataset, entities))
        result.merge(self._validate_publisher(root_dataset, entities))
        result.merge(self._validate_quantitative_values(root_dataset, entities))

        return result

    def _validate_taxons(self, dataset: dict, entities: dict) -> ValidationResult:
        """Validate that at least one Taxon is present in 'about'."""
        result = ValidationResult()

        about = dataset.get("about", [])
        about_list = about if isinstance(about, list) else [about]

        taxon_found = False
        for ref in about_list:
            ref_id = ref.get("@id") if isinstance(ref, dict) else ref
            entity = entities.get(ref_id)
            if entity and self._has_type(entity, "Taxon"):
                taxon_found = True
                # Check required fields
                if "scientificName" not in entity:
                    result.add_error(
                        f"Taxon '{ref_id}' missing required field 'scientificName'"
                    )
                break

        if not taxon_found:
            result.add_error("Dataset 'about' must include at least one Taxon")
        else:
            result.add_info("Taxon found in dataset 'about'")

        return result

    def _validate_imaging_methods(
        self, dataset: dict, entities: dict
    ) -> ValidationResult:
        """Validate that at least one imaging method (DefinedTerm) is in 'measurementMethod'."""
        result = ValidationResult()

        methods = dataset.get("measurementMethod", [])
        methods_list = methods if isinstance(methods, list) else [methods]

        defined_term_found = False
        for ref in methods_list:
            ref_id = ref.get("@id") if isinstance(ref, dict) else ref
            entity = entities.get(ref_id)
            if entity and self._has_type(entity, "DefinedTerm"):
                defined_term_found = True
                break

        if not defined_term_found:
            result.add_error(
                "Dataset 'measurementMethod' must include at least one DefinedTerm for imaging method"
            )
        else:
            result.add_info("Imaging method (DefinedTerm) found in measurementMethod")

        return result

    def _validate_authors(self, dataset: dict, entities: dict) -> ValidationResult:
        """Validate that at least one author (Person) is present."""
        result = ValidationResult()

        authors = dataset.get("author", [])
        authors_list = authors if isinstance(authors, list) else [authors]

        if not authors_list:
            result.add_error("Dataset must have at least one author")
            return result

        person_found = False
        for ref in authors_list:
            ref_id = ref.get("@id") if isinstance(ref, dict) else ref
            if not ref_id:
                continue
            entity = entities.get(ref_id)
            if entity:
                if self._has_type(entity, "Person"):
                    person_found = True
                    # Check for ORCID recommendation
                    if not str(ref_id).startswith("https://orcid.org/"):
                        result.add_warning(
                            f"Author '{ref_id}' should preferably use an ORCID identifier"
                        )
                elif self._has_type(entity, ["Organization", "Organisation"]):
                    pass  # Organizations as authors are allowed

        if not person_found:
            result.add_warning("Dataset should have at least one Person as author")
        else:
            result.add_info("Person author found")

        return result

    def _validate_publisher(self, dataset: dict, entities: dict) -> ValidationResult:
        """Validate that exactly one publisher (Organisation) is present."""
        result = ValidationResult()

        publisher = dataset.get("publisher")
        if not publisher:
            result.add_error("Dataset must have a 'publisher' property")
            return result

        pub_id = publisher.get("@id") if isinstance(publisher, dict) else publisher
        pub_entity = entities.get(pub_id)

        if not pub_entity:
            result.add_error(f"Publisher entity '{pub_id}' not found in graph")
        elif not self._has_type(pub_entity, ["Organization", "Organisation"]):
            result.add_error(
                f"Publisher '{pub_id}' must be of type Organization/Organisation"
            )
        else:
            result.add_info(f"Publisher found: {pub_entity.get('name', pub_id)}")

        return result

    def _validate_quantitative_values(
        self, dataset: dict, entities: dict
    ) -> ValidationResult:
        """Validate QuantitativeValue entities if present."""
        result = ValidationResult()

        size = dataset.get("size", [])
        size_list = size if isinstance(size, list) else [size] if size else []

        has_file_count = False
        has_bytes = False

        for ref in size_list:
            ref_id = ref.get("@id") if isinstance(ref, dict) else ref
            entity = entities.get(ref_id)

            if entity and self._has_type(entity, "QuantitativeValue"):
                unit_code = entity.get("unitCode", "")
                unit_text = entity.get("unitText", "")

                if "UO_0000189" in unit_code:  # count unit
                    has_file_count = True
                    if unit_text != "file count":
                        result.add_warning(
                            f"File count QuantitativeValue should use unitText 'file count'"
                        )

                if "UO_0000233" in unit_code:  # bytes unit
                    has_bytes = True
                    if unit_text != "bytes":
                        result.add_warning(
                            f"Bytes QuantitativeValue should use unitText 'bytes'"
                        )

        if size_list:
            if not has_file_count:
                result.add_warning(
                    "Recommended: Include QuantitativeValue for file count (unitCode: UO_0000189)"
                )
            if not has_bytes:
                result.add_warning(
                    "Recommended: Include QuantitativeValue for total bytes (unitCode: UO_0000233)"
                )
        else:
            result.add_warning(
                "Recommended: Include 'size' property with QuantitativeValues for file count and bytes"
            )

        return result

    def _has_type(self, entity: dict, type_name: str | list[str]) -> bool:
        """Check if an entity has a specific @type."""
        entity_type = entity.get("@type", [])

        if isinstance(entity_type, str):
            entity_type = [entity_type]

        if isinstance(type_name, str):
            type_name = [type_name]

        return any(t in entity_type for t in type_name)

    def _find_metadata_descriptor(self, entities: dict) -> dict | None:
        for entity in entities.values():
            if not isinstance(entity, dict):
                continue
            if not self._has_type(entity, "CreativeWork"):
                continue
            if "about" in entity:
                return entity
        return None

    def _get_id(self, ref: Any) -> str | None:
        """Extract @id from a reference (dict or string)."""
        if isinstance(ref, dict):
            return ref.get("@id")
        elif isinstance(ref, str):
            return ref
        return None


def main():
    """Command-line interface for the validator."""
    parser = argparse.ArgumentParser(
        description="Validate RO-Crate files against the GIDE Search profile",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s ro-crate-metadata.json
  %(prog)s examples/idr0002-ro-crate-metadata.json
  %(prog)s --schema custom-schema.json rocrate.json
        """,
    )
    parser.add_argument(
        "rocrate_file",
        help="Path to the RO-Crate metadata descriptor file to validate",
    )
    parser.add_argument(
        "--schema", help="Path to custom JSON schema file (optional)", type=Path
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Only show errors, not warnings or info",
    )
    parser.add_argument(
        "--json", "-j", action="store_true", help="Output results as JSON"
    )

    args = parser.parse_args()

    try:
        validator = GIDEProfileValidator(schema_path=args.schema)
        result = validator.validate(args.rocrate_file)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)

    if args.json:
        output = {
            "valid": result.valid,
            "errors": result.errors,
            "warnings": result.warnings,
            "info": result.info,
        }
        print(json.dumps(output, indent=2))
    else:
        # Print results
        if result.errors:
            print("❌ ERRORS:")
            for error in result.errors:
                print(f"  • {error}")
            print()

        if result.warnings and not args.quiet:
            print("⚠️  WARNINGS:")
            for warning in result.warnings:
                print(f"  • {warning}")
            print()

        if result.info and not args.quiet:
            print("ℹ️  INFO:")
            for info in result.info:
                print(f"  • {info}")
            print()

        if result.valid:
            print("✅ Validation PASSED")
        else:
            print("❌ Validation FAILED")

    sys.exit(0 if result.valid else 1)


if __name__ == "__main__":
    main()
