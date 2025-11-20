"""Caption timeline manager for smart replacement and deduplication."""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Literal

from mate.core.state import CaptionFrame
from mate.logging import get_logger


@dataclass
class CaptionBlock:
    """
    A caption block with timing and metadata for smart replacement.
    """
    start_time: float
    end_time: float
    text: str
    layer: Literal["A", "B", "C", "legacy"]
    confidence: float
    caption_id: str
    channel: str
    speaker: str
    is_partial: bool
    
    @property
    def duration(self) -> float:
        """Duration in seconds."""
        return self.end_time - self.start_time
    
    def overlaps(self, other: CaptionBlock) -> bool:
        """Check if this block overlaps with another."""
        return not (self.end_time <= other.start_time or self.start_time >= other.end_time)
    
    def contains_time(self, timestamp: float) -> bool:
        """Check if a timestamp falls within this block."""
        return self.start_time <= timestamp <= self.end_time


class CaptionManager:
    """
    Manages caption timeline with smart replacement logic.
    
    Implements the three-layer replacement strategy:
    - Layer C (final) replaces Layer B and A
    - Layer B (sliding window) replaces Layer A
    - Higher confidence replaces lower confidence within same layer
    """
    
    def __init__(self, max_history: int = 100):
        """
        Initialize caption manager.
        
        Args:
            max_history: Maximum number of caption blocks to keep in memory
        """
        self.logger = get_logger("caption-manager")
        self.max_history = max_history
        
        # Timeline of caption blocks per channel
        self._timeline: dict[str, list[CaptionBlock]] = {
            "mic": [],
            "speaker": [],
        }
        
        # Current active partial caption per channel
        self._active_partial: dict[str, CaptionBlock | None] = {
            "mic": None,
            "speaker": None,
        }
    
    def add_caption(self, frame: CaptionFrame) -> CaptionBlock | None:
        """
        Add or update a caption in the timeline.
        
        Returns:
            CaptionBlock if caption should be displayed, None if replaced/merged
        """
        # Create caption block from frame
        block = CaptionBlock(
            start_time=frame.start_time,
            end_time=frame.end_time or frame.start_time,
            text=frame.text,
            layer=frame.layer,
            confidence=frame.confidence,
            caption_id=frame.caption_id,
            channel=frame.channel,
            speaker=frame.speaker,
            is_partial=frame.is_partial,
        )
        
        channel = frame.channel
        timeline = self._timeline[channel]
        
        # Handle partial captions differently
        if frame.is_partial:
            return self._handle_partial(block, timeline)
        else:
            return self._handle_final(block, timeline)
    
    def _handle_partial(self, block: CaptionBlock, timeline: list[CaptionBlock]) -> CaptionBlock | None:
        """Handle partial caption (Layer A or B)."""
        channel = block.channel
        
        # Check if we should update the current partial
        current_partial = self._active_partial[channel]
        
        if current_partial is None:
            # No active partial - show this one
            self._active_partial[channel] = block
            self.logger.debug(
                "[{}] New partial from Layer {}: \"{}\"",
                block.channel,
                block.layer,
                block.text[:30]
            )
            return block
        
        # Replace if higher layer or significantly higher confidence
        layer_priority = {"A": 1, "B": 2, "C": 3, "legacy": 0}
        
        if (layer_priority[block.layer] > layer_priority[current_partial.layer] or
            block.confidence - current_partial.confidence > 0.15):
            
            # Replace current partial
            self._active_partial[channel] = block
            
            self.logger.debug(
                "[{}] Replacing Layer {} (conf={:.2f}) with Layer {} (conf={:.2f})",
                block.channel,
                current_partial.layer,
                current_partial.confidence,
                block.layer,
                block.confidence
            )
            
            return block
        
        # Check if text is similar (might be refinement)
        similarity = self._text_similarity(block.text, current_partial.text)
        
        if similarity > 0.7:
            # Similar text - merge/update
            merged_text = self._merge_texts(current_partial.text, block.text)
            block.text = merged_text
            self._active_partial[channel] = block
            
            self.logger.debug(
                "[{}] Merged partial (sim={:.2f}): \"{}\"",
                block.channel,
                similarity,
                merged_text[:30]
            )
            
            return block
        
        # Different text - might be new utterance fragment
        # Keep current partial for now
        return None
    
    def _handle_final(self, block: CaptionBlock, timeline: list[CaptionBlock]) -> CaptionBlock | None:
        """Handle final caption (Layer C)."""
        channel = block.channel
        
        # Clear active partial (final replaces it)
        self._active_partial[channel] = None
        
        # Check for overlapping blocks in timeline
        overlapping = [b for b in timeline if b.overlaps(block)]
        
        if overlapping:
            # Remove all overlapping blocks (final pass supersedes them)
            for old_block in overlapping:
                timeline.remove(old_block)
                self.logger.debug(
                    "[{}] Removed overlapping {} (replaced by Layer C)",
                    channel,
                    old_block.layer
                )
        
        # Add to timeline
        timeline.append(block)
        
        # Keep timeline sorted by start time
        timeline.sort(key=lambda b: b.start_time)
        
        # Trim history if too long
        if len(timeline) > self.max_history:
            removed = timeline.pop(0)
            self.logger.debug("[{}] Removed old caption from timeline", channel)
        
        self.logger.info(
            "[{}] Final caption added: \"{}\" ({:.1f}s)",
            channel,
            block.text[:50],
            block.duration
        )
        
        return block
    
    def _text_similarity(self, text1: str, text2: str) -> float:
        """Calculate text similarity (0.0 to 1.0)."""
        # Normalize
        t1 = text1.lower().strip()
        t2 = text2.lower().strip()
        
        if not t1 or not t2:
            return 0.0
        
        # Use sequence matcher
        matcher = difflib.SequenceMatcher(None, t1, t2)
        return matcher.ratio()
    
    def _merge_texts(self, old_text: str, new_text: str) -> str:
        """
        Merge two similar texts, preferring the longer/more complete one.
        """
        # If new text contains old text, use new (it's an extension)
        if old_text.lower() in new_text.lower():
            return new_text
        
        # If old text contains new text, keep old (new is truncated)
        if new_text.lower() in old_text.lower():
            return old_text
        
        # Check if new text extends old text
        if new_text.lower().startswith(old_text[:min(20, len(old_text))].lower()):
            return new_text
        
        # Different texts - use higher quality (newer) one
        return new_text
    
    def get_timeline(self, channel: str) -> list[CaptionBlock]:
        """Get caption timeline for a channel."""
        return self._timeline[channel].copy()
    
    def get_active_partial(self, channel: str) -> CaptionBlock | None:
        """Get currently active partial caption for a channel."""
        return self._active_partial[channel]
    
    def clear_channel(self, channel: str) -> None:
        """Clear timeline for a channel."""
        self._timeline[channel].clear()
        self._active_partial[channel] = None
        self.logger.info("[{}] Timeline cleared", channel)
    
    def get_recent_text(self, channel: str, seconds: float = 10.0) -> str:
        """
        Get recent caption text from the last N seconds.
        
        Args:
            channel: Channel to query
            seconds: How many seconds of history to include
            
        Returns:
            Combined text from recent captions
        """
        import time
        
        current_time = time.time()
        cutoff_time = current_time - seconds
        
        timeline = self._timeline[channel]
        recent_blocks = [b for b in timeline if b.end_time >= cutoff_time]
        
        if not recent_blocks:
            return ""
        
        # Combine texts
        texts = [b.text for b in recent_blocks]
        return " ".join(texts)

