"""
Tests for StepOne brand voice configuration.
"""

import pytest
from content_engine.brand_voice import BrandVoice, stepone_brand_voice


class TestBrandVoice:
    """Tests for BrandVoice class."""

    def test_tone_principles_exist(self):
        """Test brand voice has tone principles defined."""
        assert len(stepone_brand_voice.tone_principles) > 0
        assert any("Clear over clever" in p for p in stepone_brand_voice.tone_principles)

    def test_signature_vocabulary_has_keys(self):
        """Test signature vocabulary has required keys."""
        assert "insight" in stepone_brand_voice.signature_vocabulary
        assert "ideas" in stepone_brand_voice.signature_vocabulary
        assert "impact" in stepone_brand_voice.signature_vocabulary

    def test_language_to_use_not_empty(self):
        """Test language to use list is not empty."""
        assert len(stepone_brand_voice.language_to_use) > 0

    def test_language_to_avoid_not_empty(self):
        """Test language to avoid list is not empty."""
        assert len(stepone_brand_voice.language_to_avoid) > 0
        assert "creative agency" in stepone_brand_voice.language_to_avoid

    def test_tone_by_context_has_platforms(self):
        """Test tone by context covers required platforms."""
        ctx = stepone_brand_voice.tone_by_context
        assert "instagram" in ctx
        assert "linkedin" in ctx

    def test_instagram_guidelines_structure(self):
        """Test Instagram guidelines have do/dont structure."""
        guidelines = stepone_brand_voice.instagram_guidelines
        assert "do" in guidelines
        assert "dont" in guidelines


class TestBrandVoiceValidation:
    """Tests for brand voice copy validation."""

    def test_validate_clean_copy(self):
        """Test validation passes for clean copy."""
        clean_copy = "We deliver measurable impact. Our approach creates engagement."
        result = stepone_brand_voice.validate_copy(clean_copy)
        
        assert result["valid"] is True
        assert result["score"] >= 70

    def test_validate_catches_avoided_phrases(self):
        """Test validation catches language to avoid."""
        bad_copy = "We are a creative agency that provides event solutions."
        result = stepone_brand_voice.validate_copy(bad_copy)
        
        assert result["valid"] is False
        assert any("creative agency" in issue for issue in result["issues"])

    def test_validate_catches_passive_voice(self):
        """Test validation catches passive voice."""
        passive_copy = "The experience was provided by the team."
        result = stepone_brand_voice.validate_copy(passive_copy)
        
        assert result["score"] < 100  # Should be penalized

    def test_validate_catches_tentative_language(self):
        """Test validation catches tentative language."""
        tentative_copy = "We try to deliver the best results we hope to achieve."
        result = stepone_brand_voice.validate_copy(tentative_copy)
        
        assert any("tentative" in issue.lower() for issue in result["issues"])

    def test_validate_catches_vague_terms(self):
        """Test validation catches vague terms."""
        vague_copy = "We do something special with things that matter."
        result = stepone_brand_voice.validate_copy(vague_copy)
        
        assert result["score"] < 100  # Should be penalized


class TestBrandVoiceGuidance:
    """Tests for brand voice context guidance."""

    def test_get_context_guidance_instagram(self):
        """Test getting Instagram tone guidance."""
        guidance = stepone_brand_voice.get_context_guidance("instagram")
        assert len(guidance) > 0
        assert "human" in guidance.lower() or "authentic" in guidance.lower()

    def test_get_context_guidance_unknown_returns_empty(self):
        """Test unknown context returns empty string."""
        guidance = stepone_brand_voice.get_context_guidance("unknown_context")
        assert guidance == ""

    def test_apply_to_copy_replaces_avoided(self):
        """Test apply_to_copy replaces avoided phrases."""
        copy = "We are a creative agency that provides event solutions."
        result = stepone_brand_voice.apply_to_copy(copy)
        
        assert "[REDACTED]" in result


class TestBrandVoiceTemplates:
    """Tests for caption templates."""

    def test_carousel_template_structure(self):
        """Test carousel template has hook, body, cta placeholders."""
        template = stepone_brand_voice.caption_templates["carousel"]
        assert "{hook}" in template
        assert "{body}" in template
        assert "{cta}" in template

    def test_reel_template_structure(self):
        """Test reel template has hook and body."""
        template = stepone_brand_voice.caption_templates["reel"]
        assert "{hook}" in template

    def test_story_template_structure(self):
        """Test story template is simple text."""
        template = stepone_brand_voice.caption_templates["story"]
        assert "{text}" in template


class TestStepOneBrandVoiceInstance:
    """Tests for the default stepone_brand_voice singleton."""

    def test_instance_is_brand_voice(self):
        """Test stepone_brand_voice is a BrandVoice instance."""
        assert isinstance(stepone_brand_voice, BrandVoice)

    def test_instance_has_all_principles(self):
        """Test singleton has all 5 tone principles."""
        principles = stepone_brand_voice.tone_principles
        assert len(principles) == 5

    def test_instance_has_signature_vocabulary(self):
        """Test singleton has all signature vocabulary."""
        vocab = stepone_brand_voice.signature_vocabulary
        assert "insight" in vocab
        assert "ideas" in vocab
        assert "impact" in vocab
        assert len(vocab["insight"]) >= 3


class TestBrandVoiceEdgeCases:
    """Tests for edge cases in brand voice."""

    def test_empty_copy_validation(self):
        """Test validation handles empty copy."""
        result = stepone_brand_voice.validate_copy("")
        assert "issues" in result
        # Empty copy should still pass (no violations)
        assert result["score"] >= 70

    def test_long_copy_validation(self):
        """Test validation handles long copy without crashing."""
        long_copy = "We deliver " * 100 + " measurable impact."
        result = stepone_brand_voice.validate_copy(long_copy)
        assert "valid" in result

    def test_special_characters_in_copy(self):
        """Test validation handles special characters."""
        special_copy = "We deliver! @#$%^&*() impact — measuring ROI: $1M+"
        result = stepone_brand_voice.validate_copy(special_copy)
        assert "valid" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])