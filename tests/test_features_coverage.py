"""
Coverage tests for mercury.features modules:
  - template_engine.py
  - placeholders.py
  - rotation.py
"""


from mercury.features.template_engine import (
    TemplateEngine,
    TemplateConfig,
    load_template,
)
from mercury.features.placeholders import (
    PlaceholderProcessor,
    generate_identity,
    apply_placeholders,
)
from mercury.features.rotation import (
    RotationManager,
    RotationStrategy,
    RotationItem,
)


# ---------------------------------------------------------------------------
# template_engine.py
# ---------------------------------------------------------------------------


class TestTemplateEngineConfig:
    """Test TemplateEngine initialisation branches."""

    def test_init_with_template_config_object(self):
        """Line 54: `if config:` branch – pass a TemplateConfig directly."""
        config = TemplateConfig(html_content="<p>From config</p>")
        engine = TemplateEngine(config=config)
        assert engine._template_content == "<p>From config</p>"
        # config object should be stored as-is, not rebuilt
        assert engine.config is config

    def test_init_no_args_gives_empty_template(self):
        """Lines 84-85: no content, no existing path → empty string."""
        engine = TemplateEngine()
        assert engine._template_content == ""

    def test_init_non_existent_template_path_gives_empty(self):
        """Lines 84-85: template_path given but file does not exist."""
        engine = TemplateEngine(template_path="/tmp/__does_not_exist__.html")
        assert engine._template_content == ""

    def test_init_template_path_read_error(self, tmp_path, monkeypatch):
        """Lines 81-83: existing file, but open() raises an exception."""
        # Create a real file so os.path.exists passes
        html_file = tmp_path / "tpl.html"
        html_file.write_text("<p>hello</p>")

        original_open = open

        def bad_open(path, *args, **kwargs):
            if str(html_file) in str(path):
                raise IOError("simulated read error")
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr("builtins.open", bad_open)
        engine = TemplateEngine(template_path=str(html_file))
        assert engine._template_content == ""

    def test_init_with_yaml_placeholders_path(self, tmp_path):
        """Lines 102-103: placeholders_path ending in .yaml loads via yaml.safe_load."""
        placeholders_file = tmp_path / "ph.yaml"
        placeholders_file.write_text("company: AcmeCorp\ngreeting: Hello")

        engine = TemplateEngine(
            html_content="{{company}}",
            placeholders_path=str(placeholders_file),
        )
        assert engine._static_placeholders.get("company") == "AcmeCorp"

    def test_init_with_yml_placeholders_path(self, tmp_path):
        """Lines 102-103: placeholders_path ending in .yml also uses yaml."""
        placeholders_file = tmp_path / "ph.yml"
        placeholders_file.write_text("city: London")

        engine = TemplateEngine(
            html_content="{{city}}",
            placeholders_path=str(placeholders_file),
        )
        assert engine._static_placeholders.get("city") == "London"


class TestSetAndLoadTemplate:
    """Test set_template and load_template instance methods."""

    def test_set_template(self):
        """Line 114: set_template replaces _template_content."""
        engine = TemplateEngine()
        assert engine._template_content == ""
        engine.set_template("<b>New Content</b>")
        assert engine._template_content == "<b>New Content</b>"

    def test_load_template_instance_method(self, tmp_path):
        """Lines 118-119: load_template(path) updates config and reloads file."""
        html_file = tmp_path / "email.html"
        html_file.write_text("<p>Loaded from file</p>")

        engine = TemplateEngine()
        engine.load_template(str(html_file))
        assert engine._template_content == "<p>Loaded from file</p>"
        assert engine.config.template_path == str(html_file)


class TestRenderEdgeCases:
    """Test render method edge cases."""

    def test_render_no_template_content_returns_empty(self):
        """Lines 147-149: render with no content loaded returns ''."""
        engine = TemplateEngine()
        result = engine.render(recipient="test@example.com")
        assert result == ""

    def test_render_with_enable_qr_code_and_link(self):
        """Lines 166-172: enable_qr_code=True with a link generates qr_code placeholder."""
        config = TemplateConfig(
            html_content="<p>{{qr_code}}</p>",
            enable_qr_code=True,
            qr_link="https://example.com",
        )
        engine = TemplateEngine(config=config)
        # render() with a link uses the qr_generator; we just ensure no exception
        # and that {{qr_code}} is replaced (not left as a literal placeholder)
        result = engine.render(link="https://example.com/track")
        assert "{{qr_code}}" not in result

    def test_render_with_qr_code_data_url(self):
        """Lines 165-167: pre-generated qr_code_data_url is embedded."""
        engine = TemplateEngine(html_content="<p>{{qr_code}}</p>")
        result = engine.render(
            qr_code_data_url="data:image/png;base64,AAAA",
        )
        assert "data:image/png;base64,AAAA" in result
        assert "<img" in result


class TestProcessIncludes:
    """Test _process_includes method."""

    def test_process_includes_with_existing_file(self, tmp_path):
        """Lines 201-202: include resolved relative to template directory."""
        include_file = tmp_path / "partial.html"
        include_file.write_text("<footer>Footer Content</footer>")

        main_file = tmp_path / "main.html"
        main_file.write_text("<body>{{include:partial.html}}</body>")

        engine = TemplateEngine(template_path=str(main_file))
        result = engine.render()
        assert "Footer Content" in result

    def test_process_includes_with_non_existent_file(self, tmp_path):
        """Lines 210-213: missing include leaves the tag intact (returns match.group(0))."""
        main_file = tmp_path / "main.html"
        main_file.write_text("<body>{{include:missing.html}}</body>")

        engine = TemplateEngine(template_path=str(main_file))
        result = engine.render()
        # The unresolved include tag should still be present
        assert "{{include:missing.html}}" in result

    def test_process_includes_read_error(self, tmp_path, monkeypatch):
        """Lines 210-213: include file exists but read raises – tag kept."""
        include_file = tmp_path / "broken.html"
        include_file.write_text("<p>data</p>")

        main_file = tmp_path / "main.html"
        main_file.write_text("{{include:broken.html}}")

        original_open = open

        def bad_open(path, *args, **kwargs):
            if "broken.html" in str(path):
                raise IOError("disk error")
            return original_open(path, *args, **kwargs)

        engine = TemplateEngine(template_path=str(main_file))
        monkeypatch.setattr("builtins.open", bad_open)
        result = engine._process_includes(engine._template_content)
        assert "{{include:broken.html}}" in result


class TestValidateAndGetUsedPlaceholders:
    """Test validate() and get_used_placeholders() with content loaded."""

    def test_validate_with_template_content(self):
        """Line 268: validate returns dict with valid/used/missing when content exists."""
        engine = TemplateEngine(html_content="<p>{{first_name}} {{unknown_x}}</p>")
        result = engine.validate()
        assert "valid" in result
        assert "first_name" in result["used"]
        assert "unknown_x" in result["used"]
        assert result["template_size"] > 0

    def test_validate_without_template_content(self):
        """Line 268: validate with no content returns error dict."""
        engine = TemplateEngine()
        result = engine.validate()
        assert result["valid"] is False
        assert "error" in result

    def test_get_used_placeholders_with_content(self):
        """Line 283: get_used_placeholders returns list when content loaded."""
        engine = TemplateEngine(html_content="{{email}} {{company}} {{uuid}}")
        used = engine.get_used_placeholders()
        assert "email" in used
        assert "company" in used
        assert "uuid" in used

    def test_get_used_placeholders_no_content(self):
        """Line 282-283: returns [] when no template content."""
        engine = TemplateEngine()
        assert engine.get_used_placeholders() == []


class TestStandaloneLoadTemplate:
    """Test module-level load_template function (lines 310-315)."""

    def test_load_template_success(self, tmp_path):
        """Lines 311-312: reads file and returns its contents."""
        html_file = tmp_path / "good.html"
        html_file.write_text("<html>success</html>")
        content = load_template(str(html_file))
        assert content == "<html>success</html>"

    def test_load_template_failure_returns_empty(self):
        """Lines 313-315: non-existent file returns empty string."""
        content = load_template("/tmp/__nonexistent_template_xyz__.html")
        assert content == ""


# ---------------------------------------------------------------------------
# placeholders.py
# ---------------------------------------------------------------------------


class TestRegisterGenerator:
    """Test register_generator and custom generator invocation."""

    def test_register_generator_called_in_process(self):
        """Line 52 / lines 227-229: registered generator is called during process."""
        processor = PlaceholderProcessor()
        counter = {"n": 0}

        def my_gen():
            counter["n"] += 1
            return f"GEN_{counter['n']}"

        processor.register_generator("custom_ph", my_gen)
        result = processor.process("Value: {{custom_ph}}")
        assert "GEN_1" in result

    def test_register_generator_failure_is_silenced(self):
        """Lines 228-232: failing generator logs warning and uses empty string."""

        def bad_gen():
            raise RuntimeError("generator exploded")

        processor = PlaceholderProcessor()
        processor.register_generator("boom", bad_gen)
        # Should not raise; placeholder resolved to ''
        result = processor.process("X{{boom}}Y")
        assert result == "XY"


class TestEmailParsingEdgeCases:
    """Test parsing of emails without '@' (line 80 area)."""

    def test_domain_without_dot(self):
        """Line 80: domain without a dot – domain_name = domain, tld = ''."""
        processor = PlaceholderProcessor()
        placeholders = processor.get_builtin_placeholders({"email": "user@localhost"})
        assert placeholders["domain"] == "localhost"
        assert placeholders["domain_name"] == "localhost"
        assert placeholders["tld"] == ""

    def test_email_without_at_sign(self):
        """No '@' in email – local_part and domain remain empty."""
        processor = PlaceholderProcessor()
        placeholders = processor.get_builtin_placeholders({"email": "notanemail"})
        assert placeholders["local_part"] == ""
        assert placeholders["domain"] == ""


class TestFakerFallback:
    """Test fallback paths when HAS_FAKER is False."""

    def test_process_without_faker(self, monkeypatch):
        """Lines 184-186: fallback random data is used when HAS_FAKER=False."""
        import mercury.features.placeholders as ph_module

        monkeypatch.setattr(ph_module, "HAS_FAKER", False)
        processor = PlaceholderProcessor()
        placeholders = processor.get_builtin_placeholders({"email": "a@b.com"})
        # Fallback random_name is one of the hardcoded names
        fallback_names = ["John Smith", "Jane Doe", "Bob Wilson", "Alice Brown"]
        assert placeholders["random_name"] in fallback_names

    def test_generate_identity_without_faker(self, monkeypatch):
        """Lines 306-312: generate_identity falls back when HAS_FAKER=False."""
        import mercury.features.placeholders as ph_module

        monkeypatch.setattr(ph_module, "HAS_FAKER", False)
        identity = generate_identity()
        assert "first_name" in identity
        assert "last_name" in identity
        assert "full_name" in identity
        assert "@example.com" in identity["email"]
        assert "company" in identity
        assert "job_title" in identity
        assert "uuid" in identity


class TestValidatePlaceholdersWithAvailable:
    """Test validate_placeholders with available_placeholders argument (line 266)."""

    def test_validate_with_available_list(self):
        """Line 265-266: provided available_placeholders extends known set."""
        processor = PlaceholderProcessor()
        template = "{{my_custom_key}} and {{email}}"
        result = processor.validate_placeholders(
            template,
            available_placeholders=["my_custom_key"],
        )
        # my_custom_key is in the explicitly provided list → not missing
        assert "my_custom_key" not in result["missing"]
        assert result["valid"] is True

    def test_validate_missing_placeholder(self):
        """validate returns missing when key not in any source."""
        processor = PlaceholderProcessor()
        template = "{{totally_unknown_key_xyz}}"
        result = processor.validate_placeholders(template)
        assert "totally_unknown_key_xyz" in result["missing"]
        assert result["valid"] is False


class TestApplyPlaceholders:
    """Test module-level apply_placeholders function (lines 335-338)."""

    def test_apply_basic_replacement(self):
        """Lines 335-338: replaces {{key}} with value."""
        result = apply_placeholders(
            "Hello {{name}}, your code is {{code}}",
            {"name": "Alice", "code": "XYZ123"},
        )
        assert result == "Hello Alice, your code is XYZ123"

    def test_apply_none_value_becomes_empty_string(self):
        """None values are converted to empty string."""
        result = apply_placeholders("Value: {{v}}", {"v": None})
        assert result == "Value: "

    def test_apply_numeric_value(self):
        """Numeric values are stringified."""
        result = apply_placeholders("Count: {{n}}", {"n": 42})
        assert result == "Count: 42"

    def test_apply_no_placeholders(self):
        """Template without placeholders is returned unchanged."""
        tpl = "<p>No placeholders here</p>"
        result = apply_placeholders(tpl, {"unused": "data"})
        assert result == tpl


# ---------------------------------------------------------------------------
# rotation.py
# ---------------------------------------------------------------------------


class TestGetCurrent:
    """Test get_current method."""

    def test_get_current_non_existent_name(self):
        """Line 143: returns default when name not registered."""
        manager = RotationManager()
        assert manager.get_current("missing", default="fallback") == "fallback"

    def test_get_current_with_enabled_items(self):
        """Lines 150-156: returns current item without advancing index."""
        manager = RotationManager()
        manager.register("letters", ["A", "B", "C"], RotationStrategy.ROUND_ROBIN)
        # current_index starts at 0
        assert manager.get_current("letters") == "A"
        # calling again should NOT advance
        assert manager.get_current("letters") == "A"

    def test_get_current_empty_set_returns_default(self):
        """Lines 152-154: no enabled items → default."""
        manager = RotationManager()
        manager.register("empty", [], RotationStrategy.ROUND_ROBIN)
        assert manager.get_current("empty", default="X") == "X"


class TestAdvance:
    """Test advance method (line 161)."""

    def test_advance_increases_index(self):
        """advance() increments current_index."""
        manager = RotationManager()
        manager.register("items", ["A", "B", "C"], RotationStrategy.SEQUENTIAL)
        assert manager.get_current("items") == "A"
        manager.advance("items")
        assert manager.get_current("items") == "B"
        manager.advance("items")
        assert manager.get_current("items") == "C"

    def test_advance_non_existent_name_is_noop(self):
        """advance on unknown name should not raise."""
        manager = RotationManager()
        manager.advance("nonexistent")  # should not raise


class TestReset:
    """Test reset method."""

    def test_reset_specific_name(self):
        """Lines 165-169: reset(name) resets only that set."""
        manager = RotationManager()
        manager.register("A", ["x", "y"], RotationStrategy.ROUND_ROBIN)
        manager.register("B", ["1", "2"], RotationStrategy.ROUND_ROBIN)
        # Advance both
        manager.get_next("A")
        manager.get_next("A")
        manager.get_next("B")
        # Reset only A
        manager.reset("A")
        assert manager._rotation_sets["A"].current_index == 0
        # B should be unchanged
        assert manager._rotation_sets["B"].current_index == 1

    def test_reset_specific_name_clears_item_counts(self):
        """Lines 168-169: item counts reset to 0."""
        manager = RotationManager()
        manager.register("nums", [1, 2], RotationStrategy.ROUND_ROBIN)
        manager.get_next("nums")
        manager.reset("nums")
        for item in manager._rotation_sets["nums"].items:
            assert item.count == 0

    def test_reset_all(self):
        """Lines 170-174: reset() with no args resets everything."""
        manager = RotationManager()
        manager.register("X", ["a", "b"], RotationStrategy.ROUND_ROBIN)
        manager.register("Y", ["c", "d"], RotationStrategy.ROUND_ROBIN)
        manager.get_next("X")
        manager.get_next("Y")
        manager.reset()
        assert manager._rotation_sets["X"].current_index == 0
        assert manager._rotation_sets["Y"].current_index == 0

    def test_reset_nonexistent_name_is_noop(self):
        """reset(name) on unknown name should not raise."""
        manager = RotationManager()
        manager.reset("ghost")  # should not raise


class TestWeightedSelection:
    """Test _weighted_selection edge cases."""

    def test_weighted_selection_empty_list(self):
        """Line 179: empty items list returns None."""
        manager = RotationManager()
        result = manager._weighted_selection([])
        assert result is None

    def test_weighted_selection_zero_total_weight(self):
        """Line 183: all weights 0 → random.choice fallback."""
        manager = RotationManager()
        items = [RotationItem(value="A", weight=0.0), RotationItem(value="B", weight=0.0)]
        result = manager._weighted_selection(items)
        # Should still return one of the items (random choice)
        assert result in items

    def test_weighted_selection_fallback_last_item(self):
        """Line 193: return items[-1] if cumulative never exceeds r."""
        manager = RotationManager()
        items = [RotationItem(value="X", weight=1.0)]
        # With a single item, the loop must hit items[-1] path or normal path
        result = manager._weighted_selection(items)
        assert result is not None
        assert result.value == "X"

    def test_weighted_selection_returns_correct_distribution(self):
        """Basic sanity: weighted selection picks high-weight items more often."""
        manager = RotationManager()
        items = [
            RotationItem(value="heavy", weight=9.0),
            RotationItem(value="light", weight=1.0),
        ]
        results = [manager._weighted_selection(items).value for _ in range(100)]
        assert results.count("heavy") > results.count("light")


class TestGetStatisticsWithNameFilter:
    """Test get_statistics with a specific name argument (line 207)."""

    def test_get_statistics_with_name(self):
        """Line 207: returns stats dict for the named set."""
        manager = RotationManager()
        manager.register("colors", ["red", "blue"], RotationStrategy.ROUND_ROBIN)
        manager.get_next("colors")
        stats = manager.get_statistics("colors")
        assert stats["name"] == "colors"
        assert stats["strategy"] == "round_robin"
        assert stats["total_items"] == 2
        assert stats["current_index"] == 1

    def test_get_statistics_non_existent_name_returns_empty(self):
        """line 206-207: missing name returns {}."""
        manager = RotationManager()
        stats = manager.get_statistics("missing_set")
        assert stats == {}


class TestLoadConfig:
    """Test RotationManager.from_config with various strategy strings."""

    def test_load_config_valid_strategy(self):
        """from_config with a valid strategy creates the set."""
        config = {
            "subjects": {
                "items": ["Hello", "Hi"],
                "strategy": "weighted",
                "weights": [0.7, 0.3],
            }
        }
        manager = RotationManager.from_config(config)
        assert manager.is_registered("subjects")
        val = manager.get_next("subjects")
        assert val in ["Hello", "Hi"]

    def test_load_config_invalid_strategy_falls_back_to_round_robin(self):
        """Lines 262-264: unknown strategy string → ROUND_ROBIN."""
        config = {
            "set1": {
                "items": ["a", "b", "c"],
                "strategy": "totally_invalid_strategy",
            }
        }
        manager = RotationManager.from_config(config)
        assert manager.is_registered("set1")
        # First call should return "a" (round-robin order)
        assert manager.get_next("set1") == "a"

    def test_load_config_empty_items_not_registered(self):
        """Empty items list results in the set not being registered."""
        config = {
            "empty_set": {
                "items": [],
                "strategy": "round_robin",
            }
        }
        manager = RotationManager.from_config(config)
        # register() is only called if items is non-empty
        assert not manager.is_registered("empty_set")
