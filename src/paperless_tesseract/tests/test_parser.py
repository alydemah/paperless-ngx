import os
import shutil
import tempfile
import uuid
from typing import ContextManager
from unittest import mock

from django.test import override_settings
from django.test import TestCase
from documents.parsers import ParseError
from documents.parsers import run_convert
from documents.tests.utils import DirectoriesMixin
from paperless_tesseract.parsers import post_process_text
from paperless_tesseract.parsers import RasterisedDocumentParser

image_to_string_calls = []


def fake_convert(input_file, output_file, **kwargs):
    with open(input_file) as f:
        lines = f.readlines()

    for i, line in enumerate(lines):
        with open(output_file % i, "w") as f2:
            f2.write(line.strip())


class FakeImageFile(ContextManager):
    def __init__(self, fname):
        self.fname = fname

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def __enter__(self):
        return os.path.basename(self.fname)


class TestParser(DirectoriesMixin, TestCase):

    SAMPLE_FILES = os.path.join(os.path.dirname(__file__), "samples")

    def assertContainsStrings(self, content, strings):
        # Asserts that all strings appear in content, in the given order.
        indices = []
        for s in strings:
            if s in content:
                indices.append(content.index(s))
            else:
                self.fail(f"'{s}' is not in '{content}'")
        self.assertListEqual(indices, sorted(indices))

    def test_post_process_text(self):

        text_cases = [
            ("simple     string", "simple string"),
            ("simple    newline\n   testing string", "simple newline\ntesting string"),
            (
                "utf-8   строка с пробелами в конце  ",
                "utf-8 строка с пробелами в конце",
            ),
        ]

        for source, result in text_cases:
            actual_result = post_process_text(source)
            self.assertEqual(
                result,
                actual_result,
                "strip_exceess_whitespace({}) != '{}', but '{}'".format(
                    source,
                    result,
                    actual_result,
                ),
            )

    def test_get_text_from_pdf(self):
        parser = RasterisedDocumentParser(uuid.uuid4())
        text = parser.extract_text(
            None,
            os.path.join(self.SAMPLE_FILES, "simple-digital.pdf"),
        )

        self.assertContainsStrings(text.strip(), ["This is a test document."])

    def test_thumbnail(self):
        parser = RasterisedDocumentParser(uuid.uuid4())
        thumb = parser.get_thumbnail(
            os.path.join(self.SAMPLE_FILES, "simple-digital.pdf"),
            "application/pdf",
        )
        self.assertTrue(os.path.isfile(thumb))

    @mock.patch("documents.parsers.run_convert")
    def test_thumbnail_fallback(self, m):
        def call_convert(input_file, output_file, **kwargs):
            if ".pdf" in input_file:
                raise ParseError("Does not compute.")
            else:
                run_convert(input_file=input_file, output_file=output_file, **kwargs)

        m.side_effect = call_convert

        parser = RasterisedDocumentParser(uuid.uuid4())
        thumb = parser.get_thumbnail(
            os.path.join(self.SAMPLE_FILES, "simple-digital.pdf"),
            "application/pdf",
        )
        self.assertTrue(os.path.isfile(thumb))

    def test_thumbnail_encrypted(self):
        parser = RasterisedDocumentParser(uuid.uuid4())
        thumb = parser.get_thumbnail(
            os.path.join(self.SAMPLE_FILES, "encrypted.pdf"),
            "application/pdf",
        )
        self.assertTrue(os.path.isfile(thumb))

    def test_get_dpi(self):
        parser = RasterisedDocumentParser(None)

        dpi = parser.get_dpi(os.path.join(self.SAMPLE_FILES, "simple-no-dpi.png"))
        self.assertEqual(dpi, None)

        dpi = parser.get_dpi(os.path.join(self.SAMPLE_FILES, "simple.png"))
        self.assertEqual(dpi, 72)

    def test_simple_digital(self):
        parser = RasterisedDocumentParser(None)

        parser.parse(
            os.path.join(self.SAMPLE_FILES, "simple-digital.pdf"),
            "application/pdf",
        )

        self.assertTrue(os.path.isfile(parser.archive_path))

        self.assertContainsStrings(parser.get_text(), ["This is a test document."])

    def test_with_form(self):
        parser = RasterisedDocumentParser(None)

        parser.parse(
            os.path.join(self.SAMPLE_FILES, "with-form.pdf"),
            "application/pdf",
        )

        self.assertTrue(os.path.isfile(parser.archive_path))

        self.assertContainsStrings(
            parser.get_text(),
            ["Please enter your name in here:", "This is a PDF document with a form."],
        )

    @override_settings(OCR_MODE="redo")
    def test_with_form_error(self):
        parser = RasterisedDocumentParser(None)

        parser.parse(
            os.path.join(self.SAMPLE_FILES, "with-form.pdf"),
            "application/pdf",
        )

        self.assertIsNone(parser.archive_path)
        self.assertContainsStrings(
            parser.get_text(),
            ["Please enter your name in here:", "This is a PDF document with a form."],
        )

    @override_settings(OCR_MODE="skip")
    def test_signed(self):
        parser = RasterisedDocumentParser(None)

        parser.parse(os.path.join(self.SAMPLE_FILES, "signed.pdf"), "application/pdf")

        self.assertIsNone(parser.archive_path)
        self.assertContainsStrings(
            parser.get_text(),
            [
                "This is a digitally signed PDF, created with Acrobat Pro for the Paperless project to enable",
                "automated testing of signed/encrypted PDFs",
            ],
        )

    @override_settings(OCR_MODE="skip")
    def test_encrypted(self):
        parser = RasterisedDocumentParser(None)

        parser.parse(
            os.path.join(self.SAMPLE_FILES, "encrypted.pdf"),
            "application/pdf",
        )

        self.assertIsNone(parser.archive_path)
        self.assertEqual(parser.get_text(), "")

    @override_settings(OCR_MODE="redo")
    def test_with_form_error_notext(self):
        parser = RasterisedDocumentParser(None)
        parser.parse(
            os.path.join(self.SAMPLE_FILES, "with-form.pdf"),
            "application/pdf",
        )

        self.assertContainsStrings(
            parser.get_text(),
            ["Please enter your name in here:", "This is a PDF document with a form."],
        )

    @override_settings(OCR_MODE="force")
    def test_with_form_force(self):
        parser = RasterisedDocumentParser(None)

        parser.parse(
            os.path.join(self.SAMPLE_FILES, "with-form.pdf"),
            "application/pdf",
        )

        self.assertContainsStrings(
            parser.get_text(),
            ["Please enter your name in here:", "This is a PDF document with a form."],
        )

    def test_image_simple(self):
        parser = RasterisedDocumentParser(None)

        parser.parse(os.path.join(self.SAMPLE_FILES, "simple.png"), "image/png")

        self.assertTrue(os.path.isfile(parser.archive_path))

        self.assertContainsStrings(parser.get_text(), ["This is a test document."])

    def test_image_simple_alpha(self):
        parser = RasterisedDocumentParser(None)

        with tempfile.TemporaryDirectory() as tempdir:
            # Copy sample file to temp directory, as the parsing changes the file
            # and this makes it modified to Git
            sample_file = os.path.join(self.SAMPLE_FILES, "simple-alpha.png")
            dest_file = os.path.join(tempdir, "simple-alpha.png")
            shutil.copy(sample_file, dest_file)

            parser.parse(dest_file, "image/png")

            self.assertTrue(os.path.isfile(parser.archive_path))

            self.assertContainsStrings(parser.get_text(), ["This is a test document."])

    def test_image_calc_a4_dpi(self):
        parser = RasterisedDocumentParser(None)

        dpi = parser.calculate_a4_dpi(
            os.path.join(self.SAMPLE_FILES, "simple-no-dpi.png"),
        )

        self.assertEqual(dpi, 62)

    @mock.patch("paperless_tesseract.parsers.RasterisedDocumentParser.calculate_a4_dpi")
    def test_image_dpi_fail(self, m):
        m.return_value = None
        parser = RasterisedDocumentParser(None)

        def f():
            parser.parse(
                os.path.join(self.SAMPLE_FILES, "simple-no-dpi.png"),
                "image/png",
            )

        self.assertRaises(ParseError, f)

    @override_settings(OCR_IMAGE_DPI=72)
    def test_image_no_dpi_default(self):
        parser = RasterisedDocumentParser(None)

        parser.parse(os.path.join(self.SAMPLE_FILES, "simple-no-dpi.png"), "image/png")

        self.assertTrue(os.path.isfile(parser.archive_path))

        self.assertContainsStrings(
            parser.get_text().lower(),
            ["this is a test document."],
        )

    def test_multi_page(self):
        parser = RasterisedDocumentParser(None)
        parser.parse(
            os.path.join(self.SAMPLE_FILES, "multi-page-digital.pdf"),
            "application/pdf",
        )
        self.assertTrue(os.path.isfile(parser.archive_path))
        self.assertContainsStrings(
            parser.get_text().lower(),
            ["page 1", "page 2", "page 3"],
        )

    @override_settings(OCR_PAGES=2, OCR_MODE="skip")
    def test_multi_page_pages_skip(self):
        parser = RasterisedDocumentParser(None)
        parser.parse(
            os.path.join(self.SAMPLE_FILES, "multi-page-digital.pdf"),
            "application/pdf",
        )
        self.assertTrue(os.path.isfile(parser.archive_path))
        self.assertContainsStrings(
            parser.get_text().lower(),
            ["page 1", "page 2", "page 3"],
        )

    @override_settings(OCR_PAGES=2, OCR_MODE="redo")
    def test_multi_page_pages_redo(self):
        parser = RasterisedDocumentParser(None)
        parser.parse(
            os.path.join(self.SAMPLE_FILES, "multi-page-digital.pdf"),
            "application/pdf",
        )
        self.assertTrue(os.path.isfile(parser.archive_path))
        self.assertContainsStrings(
            parser.get_text().lower(),
            ["page 1", "page 2", "page 3"],
        )

    @override_settings(OCR_PAGES=2, OCR_MODE="force")
    def test_multi_page_pages_force(self):
        parser = RasterisedDocumentParser(None)
        parser.parse(
            os.path.join(self.SAMPLE_FILES, "multi-page-digital.pdf"),
            "application/pdf",
        )
        self.assertTrue(os.path.isfile(parser.archive_path))
        self.assertContainsStrings(
            parser.get_text().lower(),
            ["page 1", "page 2", "page 3"],
        )

    @override_settings(OOCR_MODE="skip")
    def test_multi_page_analog_pages_skip(self):
        parser = RasterisedDocumentParser(None)
        parser.parse(
            os.path.join(self.SAMPLE_FILES, "multi-page-images.pdf"),
            "application/pdf",
        )
        self.assertTrue(os.path.isfile(parser.archive_path))
        self.assertContainsStrings(
            parser.get_text().lower(),
            ["page 1", "page 2", "page 3"],
        )

    @override_settings(OCR_PAGES=2, OCR_MODE="redo")
    def test_multi_page_analog_pages_redo(self):
        """
        GIVEN:
            - File with text contained in images but no text layer
            - OCR of only pages 1 and 2 requested
            - OCR mode set to redo
        WHEN:
            - Document is parsed
        THEN:
            - Text of page 1 and 2 extracted
            - An archive file is created
        """
        parser = RasterisedDocumentParser(None)
        parser.parse(
            os.path.join(self.SAMPLE_FILES, "multi-page-images.pdf"),
            "application/pdf",
        )
        self.assertTrue(os.path.isfile(parser.archive_path))
        self.assertContainsStrings(parser.get_text().lower(), ["page 1", "page 2"])
        self.assertFalse("page 3" in parser.get_text().lower())

    @override_settings(OCR_PAGES=1, OCR_MODE="force")
    def test_multi_page_analog_pages_force(self):
        """
        GIVEN:
            - File with text contained in images but no text layer
            - OCR of only page 1 requested
            - OCR mode set to force
        WHEN:
            - Document is parsed
        THEN:
            - Only text of page 1 is extracted
            - An archive file is created
        """
        parser = RasterisedDocumentParser(None)
        parser.parse(
            os.path.join(self.SAMPLE_FILES, "multi-page-images.pdf"),
            "application/pdf",
        )
        self.assertTrue(os.path.isfile(parser.archive_path))
        self.assertContainsStrings(parser.get_text().lower(), ["page 1"])
        self.assertFalse("page 2" in parser.get_text().lower())
        self.assertFalse("page 3" in parser.get_text().lower())

    @override_settings(OCR_MODE="skip_noarchive")
    def test_skip_noarchive_withtext(self):
        """
        GIVEN:
            - File with existing text layer
            - OCR mode set to skip_noarchive
        WHEN:
            - Document is parsed
        THEN:
            - Text from images is extracted
            - No archive file is created
        """
        parser = RasterisedDocumentParser(None)
        parser.parse(
            os.path.join(self.SAMPLE_FILES, "multi-page-digital.pdf"),
            "application/pdf",
        )
        self.assertIsNone(parser.archive_path)
        self.assertContainsStrings(
            parser.get_text().lower(),
            ["page 1", "page 2", "page 3"],
        )

    @override_settings(OCR_MODE="skip_noarchive")
    def test_skip_noarchive_notext(self):
        """
        GIVEN:
            - File with text contained in images but no text layer
            - OCR mode set to skip_noarchive
        WHEN:
            - Document is parsed
        THEN:
            - Text from images is extracted
            - An archive file is created with the OCRd text
        """
        parser = RasterisedDocumentParser(None)
        parser.parse(
            os.path.join(self.SAMPLE_FILES, "multi-page-images.pdf"),
            "application/pdf",
        )

        self.assertContainsStrings(
            parser.get_text().lower(),
            ["page 1", "page 2", "page 3"],
        )

        self.assertIsNotNone(parser.archive_path)

    @override_settings(OCR_MODE="skip")
    def test_multi_page_mixed(self):
        """
        GIVEN:
            - File with some text contained in images and some in text layer
            - OCR mode set to skip
        WHEN:
            - Document is parsed
        THEN:
            - Text from images is extracted
            - An archive file is created with the OCRd text and the original text
        """
        parser = RasterisedDocumentParser(None)
        parser.parse(
            os.path.join(self.SAMPLE_FILES, "multi-page-mixed.pdf"),
            "application/pdf",
        )
        self.assertIsNotNone(parser.archive_path)
        self.assertTrue(os.path.isfile(parser.archive_path))
        self.assertContainsStrings(
            parser.get_text().lower(),
            ["page 1", "page 2", "page 3", "page 4", "page 5", "page 6"],
        )

        with open(os.path.join(parser.tempdir, "sidecar.txt")) as f:
            sidecar = f.read()

        self.assertIn("[OCR skipped on page(s) 4-6]", sidecar)

    @override_settings(OCR_MODE="redo")
    def test_single_page_mixed(self):
        """
        GIVEN:
            - File with some text contained in images and some in text layer
            - Text and images are mixed on the same page
            - OCR mode set to redo
        WHEN:
            - Document is parsed
        THEN:
            - Text from images is extracted
            - Full content of the file is parsed (not just the image text)
            - An archive file is created with the OCRd text and the original text
        """
        parser = RasterisedDocumentParser(None)
        parser.parse(
            os.path.join(self.SAMPLE_FILES, "single-page-mixed.pdf"),
            "application/pdf",
        )
        self.assertIsNotNone(parser.archive_path)
        self.assertTrue(os.path.isfile(parser.archive_path))
        self.assertContainsStrings(
            parser.get_text().lower(),
            [
                "this is some normal text, present on page 1 of the document.",
                "this is some text, but in an image, also on page 1.",
                "this is further text on page 1.",
            ],
        )

        with open(os.path.join(parser.tempdir, "sidecar.txt")) as f:
            sidecar = f.read().lower()

        self.assertIn("this is some text, but in an image, also on page 1.", sidecar)
        self.assertNotIn(
            "this is some normal text, present on page 1 of the document.",
            sidecar,
        )

    @override_settings(OCR_MODE="skip_noarchive")
    def test_multi_page_mixed_no_archive(self):
        """
        GIVEN:
            - File with some text contained in images and some in text layer
            - OCR mode set to skip_noarchive
        WHEN:
            - Document is parsed
        THEN:
            - Text from images is extracted
            - No archive file is created as original file contains text
        """
        parser = RasterisedDocumentParser(None)
        parser.parse(
            os.path.join(self.SAMPLE_FILES, "multi-page-mixed.pdf"),
            "application/pdf",
        )
        self.assertIsNone(parser.archive_path)
        self.assertContainsStrings(
            parser.get_text().lower(),
            ["page 4", "page 5", "page 6"],
        )

    @override_settings(OCR_MODE="skip", OCR_ROTATE_PAGES=True)
    def test_rotate(self):
        parser = RasterisedDocumentParser(None)
        parser.parse(os.path.join(self.SAMPLE_FILES, "rotated.pdf"), "application/pdf")
        self.assertContainsStrings(
            parser.get_text(),
            [
                "This is the text that appears on the first page. It’s a lot of text.",
                "Even if the pages are rotated, OCRmyPDF still gets the job done.",
                "This is a really weird file with lots of nonsense text.",
                "If you read this, it’s your own fault. Also check your screen orientation.",
            ],
        )

    def test_multi_page_tiff(self):
        """
        GIVEN:
            - Multi-page TIFF image
        WHEN:
            - Image is parsed
        THEN:
            - Text from all pages extracted
        """
        parser = RasterisedDocumentParser(None)
        parser.parse(
            os.path.join(self.SAMPLE_FILES, "multi-page-images.tiff"),
            "image/tiff",
        )
        self.assertTrue(os.path.isfile(parser.archive_path))
        self.assertContainsStrings(
            parser.get_text().lower(),
            ["page 1", "page 2", "page 3"],
        )

    def test_multi_page_tiff_alpha(self):
        """
        GIVEN:
            - Multi-page TIFF image
            - Image include an alpha channel
        WHEN:
            - Image is parsed
        THEN:
            - Text from all pages extracted
        """
        parser = RasterisedDocumentParser(None)
        parser.parse(
            os.path.join(self.SAMPLE_FILES, "multi-page-images-alpha.tiff"),
            "image/tiff",
        )
        self.assertTrue(os.path.isfile(parser.archive_path))
        self.assertContainsStrings(
            parser.get_text().lower(),
            ["page 1", "page 2", "page 3"],
        )

    def test_multi_page_tiff_alpha_srgb(self):
        """
        GIVEN:
            - Multi-page TIFF image
            - Image include an alpha channel
            - Image is srgb colorspace
        WHEN:
            - Image is parsed
        THEN:
            - Text from all pages extracted
        """
        parser = RasterisedDocumentParser(None)
        parser.parse(
            os.path.join(self.SAMPLE_FILES, "multi-page-images-alpha-rgb.tiff"),
            "image/tiff",
        )
        self.assertTrue(os.path.isfile(parser.archive_path))
        self.assertContainsStrings(
            parser.get_text().lower(),
            ["page 1", "page 2", "page 3"],
        )

    def test_ocrmypdf_parameters(self):
        parser = RasterisedDocumentParser(None)
        params = parser.construct_ocrmypdf_parameters(
            input_file="input.pdf",
            output_file="output.pdf",
            sidecar_file="sidecar.txt",
            mime_type="application/pdf",
            safe_fallback=False,
        )

        self.assertEqual(params["input_file"], "input.pdf")
        self.assertEqual(params["output_file"], "output.pdf")
        self.assertEqual(params["sidecar"], "sidecar.txt")

        with override_settings(OCR_CLEAN="none"):
            params = parser.construct_ocrmypdf_parameters("", "", "", "")
            self.assertNotIn("clean", params)
            self.assertNotIn("clean_final", params)

        with override_settings(OCR_CLEAN="clean"):
            params = parser.construct_ocrmypdf_parameters("", "", "", "")
            self.assertTrue(params["clean"])
            self.assertNotIn("clean_final", params)

        with override_settings(OCR_CLEAN="clean-final", OCR_MODE="skip"):
            params = parser.construct_ocrmypdf_parameters("", "", "", "")
            self.assertTrue(params["clean_final"])
            self.assertNotIn("clean", params)

        with override_settings(OCR_CLEAN="clean-final", OCR_MODE="redo"):
            params = parser.construct_ocrmypdf_parameters("", "", "", "")
            self.assertTrue(params["clean"])
            self.assertNotIn("clean_final", params)

        with override_settings(OCR_DESKEW=True, OCR_MODE="skip"):
            params = parser.construct_ocrmypdf_parameters("", "", "", "")
            self.assertTrue(params["deskew"])

        with override_settings(OCR_DESKEW=True, OCR_MODE="redo"):
            params = parser.construct_ocrmypdf_parameters("", "", "", "")
            self.assertNotIn("deskew", params)

        with override_settings(OCR_DESKEW=False, OCR_MODE="skip"):
            params = parser.construct_ocrmypdf_parameters("", "", "", "")
            self.assertNotIn("deskew", params)

    def test_rtl_language_detection(self):
        """
        GIVEN:
            - File with text in an RTL language
        WHEN:
            - Document is parsed
        THEN:
            - Text from the document is extracted
        """
        parser = RasterisedDocumentParser(None)
        with mock.patch.object(
            parser,
            "construct_ocrmypdf_parameters",
            wraps=parser.construct_ocrmypdf_parameters,
        ) as wrapped:

            parser.parse(
                os.path.join(self.SAMPLE_FILES, "rtl-test.pdf"),
                "application/pdf",
            )

            # There isn't a good way to actually check this working, with RTL correctly return
            #  as it would require tesseract-ocr-ara installed for everyone running the
            #  test suite.  This test does provide the coverage though and attempts to ensure
            # the force OCR happens
            self.assertIsNotNone(parser.get_text())

            self.assertEqual(parser.construct_ocrmypdf_parameters.call_count, 2)
            # Check the last call kwargs
            self.assertTrue(
                parser.construct_ocrmypdf_parameters.call_args.kwargs["safe_fallback"],
            )


class TestParserFileTypes(DirectoriesMixin, TestCase):

    SAMPLE_FILES = os.path.join(os.path.dirname(__file__), "samples")

    def test_bmp(self):
        parser = RasterisedDocumentParser(None)
        parser.parse(os.path.join(self.SAMPLE_FILES, "simple.bmp"), "image/bmp")
        self.assertTrue(os.path.isfile(parser.archive_path))
        self.assertIn("this is a test document", parser.get_text().lower())

    def test_jpg(self):
        parser = RasterisedDocumentParser(None)
        parser.parse(os.path.join(self.SAMPLE_FILES, "simple.jpg"), "image/jpeg")
        self.assertTrue(os.path.isfile(parser.archive_path))
        self.assertIn("this is a test document", parser.get_text().lower())

    @override_settings(OCR_IMAGE_DPI=200)
    def test_gif(self):
        parser = RasterisedDocumentParser(None)
        parser.parse(os.path.join(self.SAMPLE_FILES, "simple.gif"), "image/gif")
        self.assertTrue(os.path.isfile(parser.archive_path))
        self.assertIn("this is a test document", parser.get_text().lower())

    def test_tiff(self):
        parser = RasterisedDocumentParser(None)
        parser.parse(os.path.join(self.SAMPLE_FILES, "simple.tif"), "image/tiff")
        self.assertTrue(os.path.isfile(parser.archive_path))
        self.assertIn("this is a test document", parser.get_text().lower())

    @override_settings(OCR_IMAGE_DPI=72)
    def test_webp(self):
        parser = RasterisedDocumentParser(None)
        parser.parse(os.path.join(self.SAMPLE_FILES, "document.webp"), "image/webp")
        self.assertTrue(os.path.isfile(parser.archive_path))
        # OCR consistent mangles this space, oh well
        self.assertIn(
            "this is awebp document, created 11/14/2022.",
            parser.get_text().lower(),
        )
