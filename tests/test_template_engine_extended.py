
import pytest
from unittest.mock import Mock, patch, mock_open
from unified_sender.features.template_engine import TemplateEngine, TemplateConfig

class TestTemplateEngineExtended:
    """Extended tests for TemplateEngine."""

    def test_init_with_content(self):
        engine = TemplateEngine(html_content="<p>Test</p>")
        assert engine._template_content == "<p>Test</p>"

    def test_load_template_file(self):
        with patch("builtins.open", mock_open(read_data="<p>File</p>")):
            with patch("os.path.exists", return_value=True):
                engine = TemplateEngine(template_path="t.html")
                assert engine._template_content == "<p>File</p>"

    def test_load_static_placeholders_json(self):
        json_data = '{"key": "value"}'
        with patch("builtins.open", mock_open(read_data=json_data)):
            with patch("os.path.exists", return_value=True):
                engine = TemplateEngine(placeholders_path="p.json")
                assert engine._static_placeholders["key"] == "value"

    def test_process_includes(self):
        main_html = "Header {{include:footer.html}}"
        footer_html = "Footer"
        
        with patch("os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=footer_html)):
                engine = TemplateEngine(html_content=main_html)
                rendered = engine.render()
                assert "Header Footer" in rendered

    def test_process_conditionals(self):
        html = """
        {{if:show_promo}}Promo!{{else}}No Promo{{endif}}
        {{if:false_flag}}Hidden{{endif}}
        """
        engine = TemplateEngine(html_content=html)
        
        # Test True
        rendered = engine.render(extra_placeholders={"show_promo": "true", "false_flag": "false"})
        assert "Promo!" in rendered
        assert "No Promo" not in rendered
        assert "Hidden" not in rendered
        
        # Test False
        rendered = engine.render(extra_placeholders={"show_promo": "false"})
        assert "No Promo" in rendered

    def test_validate(self):
        html = "Hello {{name}}"
        engine = TemplateEngine(html_content=html)
        report = engine.validate()
        assert report['valid'] is True
        assert 'name' in report['used']  # 'placeholders' was wrong key

    def test_preview(self):
        engine = TemplateEngine(html_content="Hi {{email}}")
        prev = engine.preview("me@test.com")
        assert "Hi me@test.com" in prev

    def test_qr_code_rendering(self):
        engine = TemplateEngine(html_content="Scan {{qr_code}}")
        engine.config.enable_qr_code = True
        
        # Patch the instance method directly since engine is already initialized
        engine.qr_generator.generate_data_url = Mock(return_value="data:img")
        
        rendered = engine.render(link="http://link")
        assert 'src="data:img"' in rendered

    def test_nested_conditionals(self):
        html = "{{if:outer}}{{if:inner}}Inner{{endif}}{{endif}}"
        engine = TemplateEngine(html_content=html)
        rendered = engine.render(extra_placeholders={"outer": "true", "inner": "true"})
        assert "Inner" in rendered
