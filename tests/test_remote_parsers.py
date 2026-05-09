import json
import unittest
from pathlib import Path

from pipeline.modules import cdd, coils, hmmer, interproscan, phobius, retrieval, scanprosite, signalp, smart, uniprot_features
from services import disorderpred, iupred, jpred, netsurf, predator, protpipe_companions, psi, sable, sspred_figure, sspro, structmap, yaspin


FIXTURES = Path(__file__).parent / "fixtures"


def read_text(*parts):
    return (FIXTURES.joinpath(*parts)).read_text(encoding="utf-8")


def read_json(*parts):
    return json.loads(read_text(*parts))


class SSPredParserTests(unittest.TestCase):
    def test_jpred_jnet_parser(self):
        parsed = jpred._parse_jnet_output(read_text("sspred", "jpred.jnet"))
        self.assertEqual(parsed["pred"], "CCEHHCCHH")
        self.assertEqual(parsed["conf"], "998876655")

    def test_psipred_horiz_parser(self):
        parsed = psi._parse_horiz_output(read_text("sspred", "psi.horiz"))
        self.assertEqual(parsed["pred"], "CCCHHHHEE")
        self.assertEqual(parsed["conf"], "998876543")

    def test_sable_email_parser(self):
        parsed = sable._parse_email_message(read_text("sspred", "sable_email.txt"))
        self.assertEqual(parsed["pred"], "CCEEHHCC")
        self.assertEqual(parsed["conf"], "99887766")
        self.assertEqual(len(parsed["hconf"]), 8)

    def test_sspro_email_parser(self):
        parsed = sspro._parse_email_message(read_text("sspred", "sspro_email.txt"))
        self.assertEqual(parsed, "CCEEHHCC")

    def test_yaspin_results_parser(self):
        parsed = yaspin._parse_results_output(read_text("sspred", "yaspin_results.out"))
        self.assertEqual(parsed["pred"], "CCCCHHHE")
        self.assertEqual(parsed["conf"], "88776655")

    def test_predator_html_parser(self):
        parsed = predator._parse_html_response(read_text("sspred", "predator.html"))
        self.assertEqual(parsed, "CCEEHHCC")

    def test_netsurf_json_parser(self):
        data = read_json("sspred", "netsurf.json")
        parsed = netsurf._parse_result(data, expected_len=10)
        self.assertEqual(parsed["pred"], "CCEEHHCCCC")
        self.assertEqual(len(parsed["conf"]), 10)


class ProtPipeParserTests(unittest.TestCase):
    def test_phobius_short_output_parser(self):
        result = phobius._parse_output(read_text("protpipe", "phobius.txt"))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["tm_count"], 2)
        self.assertEqual(result["data"]["tm_helices"][0]["start"], 5)

    def test_signalp_short_output_parser(self):
        result = signalp._parse_output(read_text("protpipe", "signalp.txt"))
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["data"]["has_signal_peptide"])
        self.assertEqual(result["data"]["signal_peptide_end"], 19)

    def test_hmmer_result_parser(self):
        result = hmmer._parse_result(read_json("protpipe", "hmmer.json"))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["domains"][0]["name"], "PF01431")

    def test_cdd_hits_parser(self):
        hits = cdd._parse_hits(read_text("protpipe", "cdd_hits.txt"))
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["accession"], "cl45678")

    def test_scanprosite_html_parser(self):
        anns = scanprosite._parse_nice_html(read_text("protpipe", "scanprosite.html"))
        self.assertGreaterEqual(len(anns), 3)
        self.assertTrue(any(item["feature_type"] == "active_site" for item in anns))

    def test_smart_js_parser(self):
        anns = smart._parse_smart_js(read_text("protpipe", "smart.html"))
        self.assertEqual(len(anns), 3)
        self.assertTrue(any(item["feature_type"] == "signal_peptide" for item in anns))

    def test_interproscan_json_parser(self):
        anns = interproscan._parse_result(read_json("protpipe", "interproscan.json"))
        self.assertEqual(len(anns), 2)
        self.assertEqual(anns[0]["feature_type"], "domain")

    def test_uniprot_feature_parser(self):
        anns = uniprot_features._parse_features(read_json("protpipe", "uniprot_features.json")["features"])
        self.assertEqual(len(anns), 5)
        self.assertEqual(anns[0]["feature_type"], "domain")
        self.assertEqual(anns[1]["feature_type"], "motif")
        self.assertEqual(anns[2]["feature_type"], "binding_site")
        self.assertEqual(anns[4]["feature_type"], "low_complexity")

    def test_coils_html_parser(self):
        probs = coils._parse_probabilities(read_text("protpipe", "coils.html"))
        self.assertEqual(len(probs), 20)
        regions = coils._find_regions(probs)
        self.assertEqual(regions, [(4, 19)])

    def test_coils_result_link_extraction(self):
        html = read_text("protpipe", "coils_running.html")
        self.assertIn("/tmp/adc82ae28816.lupas", coils._extract_result_link(html))

    def test_coils_result_text_parser(self):
        probs = coils._parse_probabilities(read_text("protpipe", "coils_result.txt"))
        self.assertIsNotNone(probs)
        self.assertEqual(len(probs), 146)
        self.assertGreater(probs[127], 0.01)
        self.assertGreater(probs[140], 0.07)

    def test_retrieval_auto_detect(self):
        self.assertEqual(retrieval._detect_input_type("P04637"), "uniprot")
        self.assertEqual(retrieval._detect_input_type("XP_043476092.1"), "ncbi")
        self.assertEqual(retrieval._detect_input_type(">seq\nMKTIIALSYIFCL"), "raw_fasta")


class SSPredFigureTests(unittest.TestCase):
    def test_svg_figure_renders(self):
        if sspred_figure.svgwrite is None:
            self.skipTest("svgwrite not installed in local test environment")
        row = {
            "seq": "MKTIIALSYI",
            "jpredpred": "CCEEHHCCCC",
            "jpredconf": "9988776655",
            "jpredstat": 1,
            "psipred": "CCEEHHCCCC",
            "psiconf": "9988776655",
            "psistat": 1,
            "majorityvote": "CCEEHHCCCC",
        }
        svg = sspred_figure.render_svg(row, {
            "predictors": ["jpred", "psi"],
            "regions": [{"start": 2, "end": 6, "label": "Core"}],
        })
        self.assertIn("<svg", svg)
        self.assertIn("Consensus", svg)
        self.assertIn("Core", svg)


class DisorderPredTests(unittest.TestCase):
    def test_iupred_region_scoring(self):
        regions = iupred._score_regions([0.21, 0.34, 0.55, 0.61, 0.73, 0.80, 0.82, 0.79, 0.66, 0.41], threshold=0.5, minimum=4)
        self.assertEqual(len(regions), 1)
        self.assertEqual(regions[0]["start"], 3)
        self.assertEqual(regions[0]["end"], 9)

    def test_score_regions(self):
        regions = disorderpred._score_regions([0.1, 0.6, 0.7, 0.8, 0.2, 0.9, 0.95, 0.91], threshold=0.5, minimum=3, label="Disordered")
        self.assertEqual(len(regions), 2)
        self.assertEqual(regions[0]["start"], 2)
        self.assertEqual(regions[0]["end"], 4)

    def test_low_complexity_regions(self):
        hits = disorderpred._low_complexity_regions("QQQQQQQQQQQQAAAAAAAAGGGGGGGGGG", window=8, entropy_threshold=1.3, minimum=8)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["label"], "Low complexity")

    def test_sspred_companion_region_summary(self):
        regions = protpipe_companions._regions("CCCHHHHEECC")
        self.assertEqual(regions[0], {"type": "C", "start": 1, "end": 3})
        self.assertEqual(regions[1], {"type": "H", "start": 4, "end": 7})


class StructMapTests(unittest.TestCase):
    def test_external_link_inference(self):
        links = structmap._external_links(
            {"header": "sp|P04637|P53_HUMAN Cellular tumor antigen p53 OS=Homo sapiens"},
            [{"accession": "NP_000537.3"}],
        )
        self.assertIn("uniprot", links)
        self.assertIn("alphafold", links)
        self.assertIn("blast_top", links)

    def test_build_groups_features(self):
        data = structmap.build({
            "retrieval": {
                "sequence": "M" * 120,
                "header": "XP_043476092.1 neprilysin-3-like [Leptopilina heterotoma]",
            },
            "annotations": [
                {"feature_type": "signal_peptide", "label": "SP", "start": 1, "end": 18, "source": "Phobius"},
                {"feature_type": "domain", "label": "Peptidase", "start": 45, "end": 102, "source": "Pfam"},
                {"feature_type": "active_site", "label": "Catalytic site", "start": 77, "end": 77, "source": "CDD"},
            ],
            "blast": {"hits": []},
        }, "demo123")
        self.assertEqual(data["length"], 120)
        self.assertEqual(len(data["tracks"]), 3)
        self.assertEqual(data["stats"]["domains"], 1)


if __name__ == "__main__":
    unittest.main()
