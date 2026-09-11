from __future__ import annotations

import base64
import copy
import hashlib
import unittest
import uuid
from pathlib import Path

from tools.common import (
    duplicate_group_id,
    expected_visual_relation_id,
    jcs_bytes,
    load_json,
    media_digest,
    reviewed_content_sha256,
    reviewed_relation_sha256,
    reviewed_same_artwork_group_id,
    telegram_set_fingerprint,
)

ROOT = Path(__file__).resolve().parents[1]


class NormativeVectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.vectors = load_json(ROOT / "examples" / "test-vectors.json")

    def test_uuid_v5_vectors(self) -> None:
        namespace = uuid.UUID(self.vectors["namespace"])
        prefix = {"collection": "mxc_", "emoji": "mxe_", "membership": "mxm_"}
        for vector in self.vectors["uuid_v5"]:
            with self.subTest(vector=vector["entity_type"]):
                encoded = "\0".join(vector["components"]).encode("utf-8")
                self.assertEqual(encoded.hex(), vector["nul_joined_utf8_hex"])
                actual = prefix[vector["entity_type"]] + str(
                    uuid.uuid5(namespace, encoded.decode("utf-8"))
                )
                self.assertEqual(actual, vector["expected_id"])

    def test_telegram_set_fingerprint_vector(self) -> None:
        vector = self.vectors["telegram_set_fingerprint"]
        canonical = jcs_bytes(
            sorted(
                vector["members"],
                key=lambda item: (item["custom_emoji_id"], item["file_unique_id"]),
            )
        )
        self.assertEqual(canonical.hex(), vector["jcs_utf8_hex"])
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), vector["expected_sha256"])
        self.assertEqual(telegram_set_fingerprint(vector["members"]), vector["expected_sha256"])

    def test_media_digest_vector(self) -> None:
        vector = self.vectors["media_digest"]
        self.assertEqual(media_digest(vector["media"]), vector["expected_sha256"])
        self.assertEqual(media_digest(reversed(vector["media"])), vector["expected_sha256"])

    def test_reviewed_content_vector(self) -> None:
        vector = self.vectors["reviewed_content"]
        emoji = load_json(ROOT / "examples" / vector["source"])
        self.assertEqual(reviewed_content_sha256(emoji), vector["expected_sha256"])
        migrated = copy.deepcopy(emoji)
        migrated["fingerprints"]["items"][0]["canonical_render_sha256"] = "0" * 64
        self.assertEqual(reviewed_content_sha256(migrated), vector["expected_sha256"])

        metadata_only = copy.deepcopy(emoji)
        metadata_only["media"][0]["byte_size"] += 1
        metadata_only["media"][0]["duration_ms"] += 1
        self.assertEqual(reviewed_content_sha256(metadata_only), vector["expected_sha256"])

        changed_media = copy.deepcopy(emoji)
        changed_media["media"][0]["sha256"] = "0" * 64
        self.assertNotEqual(reviewed_content_sha256(changed_media), vector["expected_sha256"])

    def test_visual_relation_vector(self) -> None:
        vector = self.vectors["visual_relation_uuid_v5"]
        relation = load_json(ROOT / "examples" / vector["source"])
        namespace = uuid.UUID(vector["namespace"])
        self.assertEqual(expected_visual_relation_id(relation, namespace), vector["expected_id"])
        self.assertEqual(
            reviewed_relation_sha256(relation),
            vector["expected_reviewed_relation_sha256"],
        )

    def test_phash64_vectors(self) -> None:
        for vector in self.vectors["phash64"]:
            padding = "=" * ((4 - len(vector["encoded"]) % 4) % 4)
            decoded = base64.b64decode(vector["encoded"] + padding, altchars=b"-_", validate=True)
            self.assertEqual(decoded.hex(), vector["decoded_hex"])
            self.assertEqual(len(decoded), vector["sample_count"] * 8)

    def test_duplicate_group_id_vectors(self) -> None:
        vectors = self.vectors["duplicate_group_ids"]
        namespace = uuid.UUID(vectors["namespace"])
        cases = {
            "binary_media": {
                "source_sha256": vectors["binary_media"]["source_sha256"],
                "source_byte_size": vectors["binary_media"]["byte_size"],
            },
            "decoded_media": {
                "decoded_profile_id": vectors["decoded_media"]["decoded_profile_id"],
                "decoded_payload_sha256": vectors["decoded_media"]["decoded_payload_sha256"],
            },
            "binary_entity": {
                "media_set_root_sha256": vectors["binary_entity"]["media_set_root_sha256"]
            },
            "decoded_entity": {
                "decoded_profile_id": vectors["decoded_entity"]["decoded_profile_id"],
                "media_set_root_sha256": vectors["decoded_entity"]["media_set_root_sha256"],
            },
            "reviewed_same_artwork": {"members": vectors["reviewed_same_artwork"]["members"]},
        }
        for key, extra in cases.items():
            vector = vectors[key]
            actual = duplicate_group_id(
                namespace,
                group_type=vector["group_type"],
                scope=vector["scope"],
                **extra,
            )
            self.assertEqual(actual, vector["expected_id"])

        reviewed = vectors["reviewed_same_artwork"]
        self.assertEqual(
            reviewed_same_artwork_group_id(namespace, reviewed["members"]),
            reviewed["expected_id"],
        )


if __name__ == "__main__":
    unittest.main()
