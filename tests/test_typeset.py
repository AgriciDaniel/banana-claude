from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from tests._support import PNG_1X1, run_python

import banana_core
from banana_core import BananaError
from typeset import (
    MAX_FONT_BYTES,
    MAX_LAYERS_FILE_BYTES,
    MAX_TEXT_FILE_BYTES,
    compose_image,
    render_composite_svg,
    render_svg,
    typeset_image,
)


class TypesetTests(unittest.TestCase):
    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires FIFO support")
    def test_text_file_must_be_a_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "source.png"
            fifo = Path(directory) / "text.fifo"
            image.write_bytes(PNG_1X1)
            os.mkfifo(fifo)
            result = run_python(
                "typeset.py",
                "--image",
                str(image),
                "--text-file",
                str(fifo),
                "--x",
                "0",
                "--y",
                "0",
                "--font-size",
                "1",
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("typeset_io_error", result.stderr)

    def test_raster_change_after_validation_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "source.png"
            image.write_bytes(PNG_1X1)
            reference = {
                "path": str(image),
                "mime_type": "image/png",
                "bytes": len(PNG_1X1),
                "sha256": hashlib.sha256(PNG_1X1).hexdigest(),
            }

            def mutate_after_validation(
                *_args: object, **_kwargs: object
            ) -> list[dict[str, Any]]:
                image.write_bytes(PNG_1X1[:-1] + bytes([PNG_1X1[-1] ^ 1]))
                return [reference]

            with patch(
                "typeset.validate_reference_paths", side_effect=mutate_after_validation
            ):
                with self.assertRaises(BananaError) as caught:
                    render_svg(
                        image_path=image,
                        text="Exact",
                        x=0,
                        y=0,
                        font_size=1,
                        font_family="sans-serif",
                        font_weight="normal",
                        fill="#fff",
                        anchor="start",
                        line_height=1.2,
                    )
            self.assertEqual(caught.exception.code, "reference_changed")

    def test_no_force_write_does_not_replace_racing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "source.png"
            output = Path(directory) / "finished.svg"
            image.write_bytes(PNG_1X1)

            def create_competing_output(
                **_kwargs: object,
            ) -> tuple[bytes, dict[str, Any]]:
                output.write_bytes(b"competing output")
                return b"<svg/>", {}

            with patch("typeset.render_svg", side_effect=create_competing_output):
                with self.assertRaises(BananaError) as caught:
                    typeset_image(
                        image_path=image,
                        text="Exact",
                        x=0,
                        y=0,
                        font_size=1,
                        output_path=output,
                    )
            self.assertEqual(caught.exception.code, "output_exists")
            self.assertEqual(output.read_bytes(), b"competing output")

    def test_force_write_replaces_existing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "source.png"
            output = Path(directory) / "finished.svg"
            image.write_bytes(PNG_1X1)
            output.write_bytes(b"old")
            result = typeset_image(
                image_path=image,
                text="Exact",
                x=0,
                y=0,
                font_size=1,
                output_path=output,
                force=True,
            )
            self.assertTrue(result["ok"])
            self.assertTrue(output.read_bytes().startswith(b"<?xml"))

    def test_path_only_no_replace_platform_can_create_a_new_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "source.png"
            output = Path(directory) / "finished.svg"
            image.write_bytes(PNG_1X1)
            with (
                patch.object(banana_core, "_open_secure_directory", return_value=None),
                patch.object(
                    banana_core,
                    "_path_rename_without_replace_supported",
                    return_value=True,
                ),
            ):
                result = typeset_image(
                    image_path=image,
                    text="Exact",
                    x=0,
                    y=0,
                    font_size=1,
                    output_path=output,
                )
            self.assertTrue(result["ok"])
            self.assertTrue(output.read_bytes().startswith(b"<?xml"))

    def test_path_only_no_replace_race_retains_both_entries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "finished.svg"
            competing = b"competing output"

            def compete_then_fail(source: Path, destination: Path) -> None:
                output.write_bytes(competing)
                raise FileExistsError(destination)

            with (
                patch.object(
                    banana_core,
                    "_open_secure_directory",
                    return_value=None,
                ),
                patch.object(
                    banana_core,
                    "_path_rename_without_replace_supported",
                    return_value=True,
                ),
                patch.object(os, "rename", side_effect=compete_then_fail),
            ):
                with self.assertRaises(BananaError) as caught:
                    banana_core._atomic_write(
                        output,
                        b"intended output",
                        replace=False,
                    )

            self.assertEqual(caught.exception.code, "output_exists")
            self.assertEqual(output.read_bytes(), competing)
            retained = caught.exception.details["retained_artifacts"]
            self.assertEqual(
                [artifact["artifact_relationship"] for artifact in retained],
                [
                    "observed_nonmatching_destination",
                    "intended_temporary_artifact",
                ],
            )
            destination, temporary_artifact = retained
            self.assertEqual(destination["path"], str(output))
            self.assertEqual(Path(destination["path"]).read_bytes(), competing)
            temporary = Path(temporary_artifact["path"])
            self.assertEqual(temporary.read_bytes(), b"intended output")

    @unittest.skipIf(os.name == "nt", "symlink creation is not generally available")
    def test_dangling_output_symlink_is_not_followed_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "source.png"
            output = root / "requested.svg"
            victim = root / "elsewhere" / "victim.svg"
            image.write_bytes(PNG_1X1)
            output.symlink_to(victim)

            with self.assertRaises(BananaError) as caught:
                typeset_image(
                    image_path=image,
                    text="Exact",
                    x=0,
                    y=0,
                    font_size=1,
                    output_path=output,
                )

            self.assertEqual(caught.exception.code, "output_exists")
            self.assertTrue(output.is_symlink())
            self.assertFalse(victim.exists())

    @unittest.skipIf(os.name == "nt", "symlink creation is not generally available")
    def test_force_replaces_output_symlink_itself_not_its_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "source.png"
            output = root / "requested.svg"
            victim = root / "victim.svg"
            image.write_bytes(PNG_1X1)
            victim.write_bytes(b"foreign victim")
            output.symlink_to(victim)

            result = typeset_image(
                image_path=image,
                text="Exact",
                x=0,
                y=0,
                font_size=1,
                output_path=output,
                force=True,
            )

            self.assertTrue(result["ok"])
            self.assertFalse(output.is_symlink())
            self.assertTrue(output.read_bytes().startswith(b"<?xml"))
            self.assertEqual(victim.read_bytes(), b"foreign victim")

    def test_typeset_rejects_parent_identity_changes(self) -> None:
        original_match = banana_core._directory_path_matches_fd
        for parent_exists in (True, False):
            with (
                self.subTest(parent_exists=parent_exists),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                image = root / "source.png"
                image.write_bytes(PNG_1X1)
                destination = root / "approved"
                if parent_exists:
                    destination.mkdir()
                moved = root / "approved-before-swap"
                redirect = root / "redirect"
                redirect.mkdir()
                output = destination / "finished.svg"
                swapped = False

                def swap_before_publication(path: Path, descriptor: int) -> bool:
                    nonlocal swapped
                    if not swapped and Path(path) == destination:
                        destination.rename(moved)
                        destination.symlink_to(redirect, target_is_directory=True)
                        swapped = True
                    return original_match(path, descriptor)

                with patch.object(
                    banana_core,
                    "_directory_path_matches_fd",
                    side_effect=swap_before_publication,
                ):
                    with self.assertRaises(BananaError) as caught:
                        typeset_image(
                            image_path=image,
                            text="Exact",
                            x=0,
                            y=0,
                            font_size=1,
                            output_path=output,
                        )
                self.assertEqual(caught.exception.code, "output_directory_changed")
                self.assertEqual(list(redirect.iterdir()), [])
                self.assertEqual(list(moved.iterdir()), [])

    def test_webp_background_dimensions_are_supported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "source.webp"
            payload = (
                b"\x00\x00\x00\x00"
                + (2).to_bytes(3, "little")
                + (1).to_bytes(3, "little")
            )
            image.write_bytes(
                b"RIFF"
                + (22).to_bytes(4, "little")
                + b"WEBPVP8X"
                + (10).to_bytes(4, "little")
                + payload
            )
            rendered, metadata = render_svg(
                image_path=image,
                text="Exact",
                x=0,
                y=1,
                font_size=1,
                font_family="sans-serif",
                font_weight="normal",
                fill="#fff",
                anchor="start",
                line_height=1.2,
            )
            self.assertIn(b"data:image/webp;base64,", rendered)
            self.assertEqual((metadata["width"], metadata["height"]), (3, 2))

    def test_svg_is_deterministic_exact_and_self_contained(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "source.png"
            image.write_bytes(PNG_1X1)
            arguments: dict[str, Any] = {
                "image_path": image,
                "text": "Exact & <safe>\nSecond line",
                "x": 0.5,
                "y": 0.25,
                "font_size": 0.1,
                "font_family": "Inter",
                "font_weight": "700",
                "fill": "#ffffff",
                "anchor": "middle",
                "line_height": 1.2,
            }
            first, metadata = render_svg(**arguments)
            second, _ = render_svg(**arguments)
            self.assertEqual(first, second)
            text = first.decode("utf-8")
            self.assertIn("Exact &amp; &lt;safe&gt;", text)
            self.assertIn("data:image/png;base64,", text)
            self.assertNotIn(str(image), text)
            self.assertEqual(metadata["width"], 1)
            self.assertEqual(metadata["height"], 1)

    def test_cli_writes_private_svg_and_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "source.png"
            output = Path(directory) / "finished.svg"
            image.write_bytes(PNG_1X1)
            arguments = (
                "--image",
                str(image),
                "--text",
                "Exact copy",
                "--x",
                "0.1",
                "--y",
                "0.5",
                "--font-size",
                "0.2",
                "--output",
                str(output),
            )
            result = run_python("typeset.py", *arguments)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(
                payload["automated_visual_review_status"],
                "blocked_pending_raster_preview",
            )
            self.assertTrue(payload["raster_preview_required"])
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)

            repeated = run_python("typeset.py", *arguments)
            self.assertEqual(repeated.returncode, 1)
            self.assertIn("output_exists", repeated.stderr)

    def test_typeset_output_paths_reject_invisible_controls_and_surrogates(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "source.png"
            image.write_bytes(PNG_1X1)
            for label, character in (
                ("terminal control", "\x1b"),
                ("bidirectional control", "\u202e"),
                ("unpaired surrogate", "\ud800"),
            ):
                with self.subTest(label=label):
                    output = str(Path(directory) / f"unsafe{character}.svg")
                    with self.assertRaises(BananaError) as caught:
                        typeset_image(
                            image_path=image,
                            text="Exact",
                            x=0,
                            y=0,
                            font_size=1,
                            output_path=output,
                        )
                    self.assertEqual(caught.exception.code, "unsafe_approval_text")

            with self.assertRaises(BananaError) as caught:
                compose_image(
                    image_path=image,
                    layers=[
                        {
                            "type": "text",
                            "text": "Exact",
                            "x": 0,
                            "y": 0,
                            "font_size": 1,
                        }
                    ],
                    output_path=str(Path(directory) / "unsafe\u202e.svg"),
                )
            self.assertEqual(caught.exception.code, "unsafe_approval_text")

    def test_invalid_raster_signature_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "fake.png"
            image.write_bytes(b"not a png")
            with self.assertRaises(BananaError) as caught:
                render_svg(
                    image_path=image,
                    text="Exact",
                    x=0,
                    y=0,
                    font_size=1,
                    font_family="sans-serif",
                    font_weight="normal",
                    fill="#fff",
                    anchor="start",
                    line_height=1.2,
                )
            self.assertEqual(caught.exception.code, "invalid_reference_signature")

    def test_ordered_composite_supports_distinct_text_hierarchy_and_raster_logo(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "source.png"
            logo = Path(directory) / "logo.png"
            image.write_bytes(PNG_1X1)
            logo.write_bytes(PNG_1X1)
            layers = [
                {
                    "type": "image",
                    "name": "approved logo",
                    "path": str(logo),
                    "x": 0,
                    "y": 0,
                    "width": 0.25,
                    "height": 0.25,
                    "fit": "contain",
                },
                {
                    "type": "text",
                    "name": "headline",
                    "text": "HEADLINE",
                    "x": 0.5,
                    "y": 0.4,
                    "font_size": 0.2,
                    "font_weight": "700",
                    "fill": "#ffffff",
                    "anchor": "middle",
                },
                {
                    "type": "text",
                    "name": "legal",
                    "text": "Exact legal copy",
                    "x": 0.5,
                    "y": 0.9,
                    "font_size": 0.05,
                    "fill": "#000000",
                    "anchor": "middle",
                },
            ]
            first, metadata = render_composite_svg(image_path=image, layers=layers)
            second, _ = render_composite_svg(image_path=image, layers=layers)
            self.assertEqual(first, second)
            rendered = first.decode("utf-8")
            self.assertEqual(rendered.count("<text "), 2)
            self.assertEqual(rendered.count("data:image/png;base64,"), 2)
            self.assertIn("HEADLINE", rendered)
            self.assertIn("Exact legal copy", rendered)
            self.assertEqual(metadata["layer_count"], 3)
            self.assertEqual(metadata["image_layer_count"], 1)
            self.assertEqual(metadata["text_layer_count"], 2)

    def test_composite_rejects_svg_asset_and_unknown_layer_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "source.png"
            svg = Path(directory) / "logo.svg"
            image.write_bytes(PNG_1X1)
            svg.write_text("<svg/>", encoding="utf-8")
            with self.assertRaises(BananaError) as caught:
                render_composite_svg(
                    image_path=image,
                    layers=[
                        {
                            "type": "image",
                            "path": str(svg),
                            "x": 0,
                            "y": 0,
                            "width": 1,
                            "height": 1,
                        }
                    ],
                )
            self.assertEqual(caught.exception.code, "unsupported_reference_type")
            with self.assertRaises(BananaError) as caught:
                render_composite_svg(
                    image_path=image,
                    layers=[
                        {
                            "type": "text",
                            "text": "Exact",
                            "x": 0,
                            "y": 0,
                            "font_size": 1,
                            "typo": True,
                        }
                    ],
                )
            self.assertEqual(caught.exception.code, "invalid_layer")

    def test_composite_rejects_xml_control_characters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "source.png"
            image.write_bytes(PNG_1X1)
            with self.assertRaises(BananaError) as caught:
                render_composite_svg(
                    image_path=image,
                    layers=[
                        {
                            "type": "text",
                            "text": "bad\x00copy",
                            "x": 0,
                            "y": 0,
                            "font_size": 1,
                        }
                    ],
                )
            self.assertEqual(caught.exception.code, "invalid_text")

    def test_composite_rejects_overlarge_and_derived_nonfinite_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "source.png"
            image.write_bytes(PNG_1X1)
            for font_size, line_height in (
                (10**4000, 1),
                (1e308, 1e308),
            ):
                with self.subTest(font_size=font_size, line_height=line_height):
                    with self.assertRaises(BananaError) as caught:
                        render_composite_svg(
                            image_path=image,
                            layers=[
                                {
                                    "type": "text",
                                    "text": "first\nsecond",
                                    "x": 0,
                                    "y": 0,
                                    "font_size": font_size,
                                    "line_height": line_height,
                                }
                            ],
                        )
                    self.assertEqual(caught.exception.code, "invalid_layer")

    def test_cli_bounds_text_and_layers_files_before_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "source.png"
            image.write_bytes(PNG_1X1)
            for label, option, limit, code in (
                ("text", "--text-file", MAX_TEXT_FILE_BYTES, "text_file_too_large"),
                (
                    "layers",
                    "--layers-file",
                    MAX_LAYERS_FILE_BYTES,
                    "layers_file_too_large",
                ),
            ):
                with self.subTest(label=label):
                    source = Path(directory) / f"oversized-{label}"
                    with source.open("wb") as handle:
                        handle.seek(limit)
                        handle.write(b"x")
                    arguments = ["--image", str(image), option, str(source)]
                    if option == "--text-file":
                        arguments.extend(["--x", "0", "--y", "0", "--font-size", "1"])
                    result = run_python("typeset.py", *arguments)
                    self.assertEqual(result.returncode, 1)
                    self.assertIn(code, result.stderr)

    def test_layers_file_rejects_excessive_json_nesting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "source.png"
            layers = Path(directory) / "layers.json"
            image.write_bytes(PNG_1X1)
            layers.write_bytes(b"[" * 100_000 + b"0" + b"]" * 100_000)
            result = run_python(
                "typeset.py",
                "--image",
                str(image),
                "--layers-file",
                str(layers),
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("invalid_layers", result.stderr)

    def test_font_size_is_bounded_before_full_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "source.png"
            font = Path(directory) / "oversized.ttf"
            image.write_bytes(PNG_1X1)
            with font.open("wb") as handle:
                handle.seek(MAX_FONT_BYTES)
                handle.write(b"x")
            with self.assertRaises(BananaError) as caught:
                render_svg(
                    image_path=image,
                    text="Exact",
                    x=0,
                    y=0,
                    font_size=1,
                    font_family="sans-serif",
                    font_path=font,
                    font_weight="normal",
                    fill="#fff",
                    anchor="start",
                    line_height=1.2,
                )
            self.assertEqual(caught.exception.code, "invalid_font_size")


if __name__ == "__main__":
    unittest.main()
