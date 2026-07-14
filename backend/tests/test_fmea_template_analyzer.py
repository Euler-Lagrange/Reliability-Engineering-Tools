"""Focused regressions for FMEA template package preflight."""

from __future__ import annotations

import base64
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZIP_DEFLATED, ZipFile


_CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_DOCUMENT_REL_NS = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
)
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _with_embedded_image(source_path: Path) -> Path:
    """Add one fully related image drawing to an existing XLSX package."""
    output_path = source_path.with_name("preserve_target_with_image.xlsx")
    with ZipFile(source_path) as source:
        parts = {name: source.read(name) for name in source.namelist()}

    worksheet_path = "xl/worksheets/sheet1.xml"
    worksheet = ElementTree.fromstring(parts[worksheet_path])
    worksheet.append(ElementTree.Element(
        f"{{{_SPREADSHEET_NS}}}drawing",
        {f"{{{_DOCUMENT_REL_NS}}}id": "rIdImageDrawing"},
    ))
    parts[worksheet_path] = ElementTree.tostring(
        worksheet, encoding="utf-8", xml_declaration=True
    )

    sheet_rels_path = "xl/worksheets/_rels/sheet1.xml.rels"
    sheet_rels = ElementTree.Element(f"{{{_PACKAGE_REL_NS}}}Relationships")
    ElementTree.SubElement(
        sheet_rels,
        f"{{{_PACKAGE_REL_NS}}}Relationship",
        {
            "Id": "rIdImageDrawing",
            "Type": f"{_DOCUMENT_REL_NS}/drawing",
            "Target": "../drawings/drawing1.xml",
        },
    )
    parts[sheet_rels_path] = ElementTree.tostring(
        sheet_rels, encoding="utf-8", xml_declaration=True
    )

    parts["xl/drawings/drawing1.xml"] = f"""<?xml version="1.0" encoding="UTF-8"?>
<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
          xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
          xmlns:r="{_DOCUMENT_REL_NS}">
  <xdr:oneCellAnchor>
    <xdr:from><xdr:col>0</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>0</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>
    <xdr:ext cx="9525" cy="9525"/>
    <xdr:pic>
      <xdr:nvPicPr><xdr:cNvPr id="1" name="Picture 1"/><xdr:cNvPicPr/></xdr:nvPicPr>
      <xdr:blipFill><a:blip r:embed="rId1"/><a:stretch><a:fillRect/></a:stretch></xdr:blipFill>
      <xdr:spPr><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></xdr:spPr>
    </xdr:pic>
    <xdr:clientData/>
  </xdr:oneCellAnchor>
</xdr:wsDr>
""".encode("utf-8")
    parts["xl/drawings/_rels/drawing1.xml.rels"] = f"""<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="{_PACKAGE_REL_NS}">
  <Relationship Id="rId1" Type="{_DOCUMENT_REL_NS}/image" Target="../media/image1.png"/>
</Relationships>
""".encode("utf-8")
    parts["xl/media/image1.png"] = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC"
        "AAAAC0lEQVR42mP8/x8AAusB9Y9ZlN8AAAAASUVORK5CYII="
    )

    content_types = ElementTree.fromstring(parts["[Content_Types].xml"])
    ElementTree.SubElement(
        content_types,
        f"{{{_CONTENT_TYPES_NS}}}Default",
        {"Extension": "png", "ContentType": "image/png"},
    )
    ElementTree.SubElement(
        content_types,
        f"{{{_CONTENT_TYPES_NS}}}Override",
        {
            "PartName": "/xl/drawings/drawing1.xml",
            "ContentType": (
                "application/vnd.openxmlformats-officedocument.drawing+xml"
            ),
        },
    )
    parts["[Content_Types].xml"] = ElementTree.tostring(
        content_types, encoding="utf-8", xml_declaration=True
    )

    with ZipFile(output_path, "w", compression=ZIP_DEFLATED) as output:
        for name, content in parts.items():
            output.writestr(name, content)
    return output_path


def test_analyzer_warns_when_no_pillow_load_drops_embedded_image(
    monkeypatch,
    preserve_target_factory,
) -> None:
    from openpyxl.reader import drawings

    from fmea.fmea_template_analyzer import analyze_template

    fixture = preserve_target_factory()
    image_workbook = _with_embedded_image(fixture.path)
    monkeypatch.setattr(drawings, "PILImage", False)
    logs: list[str] = []

    _template_map, workbook = analyze_template(
        str(image_workbook), sheet_name="FMEA", log_func=logs.append
    )
    try:
        assert all(not getattr(sheet, "_images", ()) for sheet in workbook.worksheets)
        warnings = [
            message
            for message in logs
            if "Template analysis WARNING:" in message
        ]
        assert len(warnings) == 1
        assert "images/shapes" in warnings[0]
        assert "charts" not in warnings[0]
    finally:
        workbook.close()
