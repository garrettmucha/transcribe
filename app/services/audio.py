"""Audio processing utilities built around faster-whisper and pyannote."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from app.observability.logging import get_logger

logger = get_logger(__name__)


class AudioProcessor:
    """Audio processing and transcription service."""
    
    def __init__(self):
        self.whisper_model_name = os.getenv("WHISPER_MODEL", "medium")
        self.whisper_beam_size = int(os.getenv("WHISPER_BEAM_SIZE", "5"))
        self.temp_dir = os.getenv("TEMP_DIR", "/tmp/transcribe")
        self.enable_diarization = os.getenv("ENABLE_DIARIZATION", "true").lower() == "true"
        self.max_speakers = int(os.getenv("MAX_SPEAKERS", "10"))
        
        # Ensure temp directory exists
        os.makedirs(self.temp_dir, exist_ok=True)
        
        # Initialize models (lazy loading)
        self._whisper_model = None
        self._diarization_pipeline = None
    
    def get_whisper_model(self) -> WhisperModel:
        """Get or initialize Whisper model with fallback (thread-safe lazy loading)."""
        if self._whisper_model is None:
            logger.info(f"Loading Whisper model: {self.whisper_model_name}")

            try:
                from faster_whisper import WhisperModel  # type: ignore

                # faster-whisper downloads from Hugging Face Hub:
                # - small: ~244MB (guillaumekln/faster-whisper-small)
                # - medium: ~769MB (guillaumekln/faster-whisper-medium)
                # - large: ~1550MB (guillaumekln/faster-whisper-large)
                # Models are cached in ~/.cache/huggingface/hub/
                
                self._whisper_model = WhisperModel(
                    self.whisper_model_name,
                    device="cpu",
                    compute_type="int8",  # CPU-optimized
                    download_root=os.getenv("WHISPER_CACHE_DIR", None)  # Custom cache location
                )
                logger.info(f"Whisper model '{self.whisper_model_name}' loaded successfully")
            except Exception as e:
                logger.warning(f"Failed to load model '{self.whisper_model_name}': {e}")
                
                # Fallback to small model if medium fails
                if self.whisper_model_name != "small":
                    logger.info("Falling back to 'small' model...")
                    try:
                        from faster_whisper import WhisperModel  # type: ignore

                        self._whisper_model = WhisperModel(
                            "small",
                            device="cpu",
                            compute_type="int8",
                            download_root=os.getenv("WHISPER_CACHE_DIR", None)
                        )
                        self.whisper_model_name = "small"  # Update for diagnostics
                        logger.info("Fallback to 'small' model successful")
                    except Exception as fallback_error:
                        logger.error(f"Fallback model also failed: {fallback_error}")
                        raise
                else:
                    raise
        
        return self._whisper_model
    
    def get_diarization_pipeline(self):
        """Get or initialize speaker diarization pipeline."""
        if not self.enable_diarization:
            return None
            
        if self._diarization_pipeline is None:
            try:
                logger.info("Loading speaker diarization pipeline...")
                from pyannote.audio import Pipeline  # type: ignore
                
                # Use the pre-trained speaker diarization pipeline
                self._diarization_pipeline = Pipeline.from_pretrained(
                    "pyannote/speaker-diarization-3.1",
                    use_auth_token=os.getenv("HUGGINGFACE_TOKEN")  # Optional: for gated models
                )
                logger.info("Speaker diarization pipeline loaded successfully")
            except Exception as e:
                logger.error(f"Failed to load diarization pipeline: {e}")
                logger.warning("Speaker diarization will be disabled")
                self.enable_diarization = False
                return None
        
        return self._diarization_pipeline
    
    async def probe_duration(self, file_content: bytes, filename: str) -> float:
        """
        Probe audio duration using ffprobe.
        Returns duration in seconds.
        """
        with tempfile.NamedTemporaryFile(suffix=self._get_file_extension(filename)) as temp_file:
            temp_file.write(file_content)
            temp_file.flush()

            def probe_with_ffmpeg() -> float:
                import ffmpeg  # type: ignore

                probe_result = ffmpeg.probe(temp_file.name)
                duration = float(probe_result['streams'][0]['duration'])
                return duration

            loop = asyncio.get_running_loop()

            try:
                return await loop.run_in_executor(None, probe_with_ffmpeg)
            except ModuleNotFoundError:
                logger.warning("ffmpeg module not available, using wave fallback")
                return await loop.run_in_executor(None, self._probe_duration_wave, temp_file.name)
            except Exception as e:
                logger.error(f"ffprobe failed: {e}")
                raise ValueError(f"Invalid audio file: {e}")

    def _probe_duration_wave(self, file_path: str) -> float:
        """Fallback duration probe using Python's wave module."""

        try:
            import wave

            with wave.open(file_path, "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                if rate <= 0:
                    raise ValueError("Invalid audio sample rate")
                return frames / float(rate)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error(f"Wave probe failed: {exc}")
            raise ValueError(f"Invalid audio file: {exc}")
    
    async def normalize_audio(
        self, 
        input_file: str, 
        output_file: str
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Normalize audio to 16kHz mono WAV format.
        Returns (duration_seconds, metadata).
        """
        def normalize():
            try:
                import ffmpeg  # type: ignore

                # Get input info
                probe_result = ffmpeg.probe(input_file)
                input_duration = float(probe_result['streams'][0]['duration'])
                
                # Convert to 16kHz mono WAV
                (
                    ffmpeg
                    .input(input_file)
                    .output(
                        output_file,
                        acodec='pcm_s16le',
                        ac=1,  # mono
                        ar=16000,  # 16kHz sample rate
                        loglevel='error'
                    )
                    .overwrite_output()
                    .run()
                )
                
                # Verify output
                output_probe = ffmpeg.probe(output_file)
                output_duration = float(output_probe['streams'][0]['duration'])
                
                metadata = {
                    'input_duration': input_duration,
                    'output_duration': output_duration,
                    'sample_rate': 16000,
                    'channels': 1,
                    'codec': 'pcm_s16le'
                }
                
                logger.debug(f"Audio normalized: {input_duration:.2f}s -> {output_duration:.2f}s")
                return output_duration, metadata
                
            except Exception as e:
                logger.error(f"Audio normalization failed: {e}")
                raise
        
        return await asyncio.get_event_loop().run_in_executor(None, normalize)
    
    async def transcribe_audio(
        self,
        audio_file: str,
        language: Optional[str] = None,
        diarize: bool = False
    ) -> Tuple[str, str, Dict[str, Any]]:
        """
        Transcribe audio using Whisper with optional speaker diarization.
        Returns (transcript, vtt_captions, metadata).
        """
        def transcribe():
            try:
                model = self.get_whisper_model()

                # Transcribe with Whisper
                transcribe_start = time.time()
                segments, info = model.transcribe(
                    audio_file,
                    language=language,
                    beam_size=self.whisper_beam_size,
                    word_timestamps=True,
                    vad_filter=True
                )

                # Convert segments to list for processing
                segments_list = list(segments)
                
                # Perform speaker diarization if requested
                speaker_segments = None
                if diarize and self.enable_diarization:
                    speaker_segments = self._perform_diarization(audio_file)
                
                # Process segments and assign speakers
                transcript_lines = []
                vtt_lines = ["WEBVTT", ""]
                
                if diarize and speaker_segments:
                    vtt_lines.append("NOTE Speaker identification enabled")
                    vtt_lines.append("")
                
                for segment in segments_list:
                    text = segment.text.strip()
                    if not text:
                        continue
                    
                    # Determine speaker for this segment
                    speaker = None
                    if diarize and speaker_segments:
                        speaker = self._assign_speaker_to_segment(
                            segment.start, segment.end, speaker_segments
                        )
                    
                    # Format transcript with speaker labels
                    if speaker:
                        transcript_line = f"[{speaker}] {text}"
                    else:
                        transcript_line = text
                    transcript_lines.append(transcript_line)
                    
                    # Format VTT captions with speaker labels
                    start_time = self._format_timestamp(segment.start)
                    end_time = self._format_timestamp(segment.end)
                    
                    vtt_lines.append(f"{start_time} --> {end_time}")
                    if speaker:
                        vtt_lines.append(f"<v {speaker}>{text}")
                    else:
                        vtt_lines.append(text)
                    vtt_lines.append("")
                
                transcript = "\n".join(transcript_lines)
                vtt_captions = "\n".join(vtt_lines)
                
                # Build metadata
                metadata = {
                    'language': info.language,
                    'language_probability': info.language_probability,
                    'duration': info.duration,
                    'segments_count': len(segments_list),
                    'model_used': self.whisper_model_name,
                    'beam_size': self.whisper_beam_size,
                    'diarization_enabled': diarize and self.enable_diarization,
                    'transcription_time': time.time() - transcribe_start,
                }
                
                # Add speaker information if diarization was performed
                if diarize and speaker_segments:
                    unique_speakers = set()
                    for segment in speaker_segments:
                        unique_speakers.add(segment['speaker'])
                    
                    metadata['speakers'] = {
                        'count': len(unique_speakers),
                        'labels': sorted(list(unique_speakers)),
                        'diarization_method': 'pyannote'
                    }
                
                logger.info(f"Transcription completed: {len(transcript)} chars, {info.language}, speakers: {metadata.get('speakers', {}).get('count', 'N/A')}")
                return transcript, vtt_captions, metadata
                
            except Exception as e:
                logger.error(f"Transcription failed: {e}")
                raise
        
        return await asyncio.get_event_loop().run_in_executor(None, transcribe)
    
    def _perform_diarization(self, audio_file: str) -> Optional[list]:
        """Perform speaker diarization on audio file."""
        try:
            pipeline = self.get_diarization_pipeline()
            if not pipeline:
                return None
            
            logger.info("Performing speaker diarization...")
            diarization = pipeline(audio_file)
            
            # Convert diarization result to list of segments
            speaker_segments = []
            for turn, _, speaker in diarization.itertracks(yield_label=True):
                speaker_segments.append({
                    'start': turn.start,
                    'end': turn.end,
                    'speaker': f"Speaker {speaker.split('_')[-1]}"  # Clean up speaker label
                })
            
            # Sort segments by start time
            speaker_segments.sort(key=lambda x: x['start'])
            
            logger.info(f"Diarization completed: {len(speaker_segments)} speaker segments found")
            return speaker_segments
            
        except Exception as e:
            logger.error(f"Speaker diarization failed: {e}")
            return None
    
    def _assign_speaker_to_segment(self, start_time: float, end_time: float, speaker_segments: list) -> Optional[str]:
        """Assign speaker to a transcription segment based on time overlap."""
        segment_duration = end_time - start_time
        best_speaker = None
        best_overlap = 0
        
        for speaker_seg in speaker_segments:
            # Calculate overlap between transcription segment and speaker segment
            overlap_start = max(start_time, speaker_seg['start'])
            overlap_end = min(end_time, speaker_seg['end'])
            overlap_duration = max(0, overlap_end - overlap_start)
            
            # Calculate overlap ratio
            overlap_ratio = overlap_duration / segment_duration
            
            # Use speaker with highest overlap (must be at least 50%)
            if overlap_ratio > best_overlap and overlap_ratio >= 0.5:
                best_overlap = overlap_ratio
                best_speaker = speaker_seg['speaker']
        
        return best_speaker
    
    def _format_timestamp(self, seconds: float) -> str:
        """Format timestamp for VTT captions."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"
    
    def _get_file_extension(self, filename: str) -> str:
        """Get file extension with dot."""
        return Path(filename).suffix or ".tmp"
    
    async def process_audio_file(
        self,
        file_content: bytes,
        filename: str,
        language: Optional[str] = None,
        diarize: bool = False
    ) -> Tuple[str, str, float, Dict[str, Any]]:
        """
        Complete audio processing pipeline.
        Returns (transcript, vtt_captions, duration, metadata).
        """
        temp_input = None
        temp_normalized = None
        
        try:
            # Create temporary files
            input_suffix = self._get_file_extension(filename)
            temp_input = tempfile.NamedTemporaryFile(
                suffix=input_suffix, 
                dir=self.temp_dir, 
                delete=False
            )
            temp_normalized = tempfile.NamedTemporaryFile(
                suffix=".wav", 
                dir=self.temp_dir, 
                delete=False
            )
            
            # Write input file
            temp_input.write(file_content)
            temp_input.flush()
            temp_input.close()
            
            # Normalize audio
            duration, norm_metadata = await self.normalize_audio(
                temp_input.name, 
                temp_normalized.name
            )
            temp_normalized.close()
            
            # Transcribe
            transcript, vtt_captions, whisper_metadata = await self.transcribe_audio(
                temp_normalized.name,
                language=language,
                diarize=diarize
            )
            
            # Combine metadata
            metadata = {
                'processing': {
                    'normalization': norm_metadata,
                    'transcription': whisper_metadata
                },
                'file_info': {
                    'original_filename': filename,
                    'file_size_bytes': len(file_content)
                }
            }
            
            return transcript, vtt_captions, duration, metadata
            
        finally:
            # Cleanup temporary files
            for temp_file in [temp_input, temp_normalized]:
                if temp_file and os.path.exists(temp_file.name):
                    try:
                        os.unlink(temp_file.name)
                    except OSError as e:
                        logger.warning(f"Failed to cleanup temp file {temp_file.name}: {e}")


class TextProcessor:
    """Text processing for summarization and topic extraction."""
    
    def __init__(self):
        self.spacy_model = None
        self.keybert_model = None
    
    def get_spacy_model(self):
        """Get or load spaCy model."""
        if self.spacy_model is None:
            try:
                import spacy
                self.spacy_model = spacy.load("en_core_web_sm")
            except OSError:
                logger.warning("spaCy model not found, using basic text processing")
                self.spacy_model = None
        return self.spacy_model
    
    def get_keybert_model(self):
        """Get or load KeyBERT model."""
        if self.keybert_model is None:
            try:
                from keybert import KeyBERT
                self.keybert_model = KeyBERT()
            except ImportError:
                logger.warning("KeyBERT not available, using basic keyword extraction")
                self.keybert_model = None
        return self.keybert_model
    
    async def extract_topics(self, text: str, max_topics: int = 10) -> Dict[str, Any]:
        """Extract topics and keywords from text."""
        def extract():
            try:
                topics = []
                
                # Try KeyBERT first
                keybert = self.get_keybert_model()
                if keybert and len(text) > 50:
                    try:
                        keywords = keybert.extract_keywords(
                            text, 
                            keyphrase_ngram_range=(1, 3),
                            stop_words='english',
                            top_k=max_topics
                        )
                        topics = [{"keyword": kw, "score": score} for kw, score in keywords]
                    except Exception as e:
                        logger.warning(f"KeyBERT extraction failed: {e}")
                
                # Fallback to spaCy noun phrases
                if not topics:
                    spacy_model = self.get_spacy_model()
                    if spacy_model:
                        try:
                            doc = spacy_model(text)
                            noun_phrases = [chunk.text.lower() for chunk in doc.noun_chunks]
                            # Count frequency and take top ones
                            from collections import Counter
                            phrase_counts = Counter(noun_phrases)
                            topics = [
                                {"keyword": phrase, "score": count / len(noun_phrases)}
                                for phrase, count in phrase_counts.most_common(max_topics)
                            ]
                        except Exception as e:
                            logger.warning(f"spaCy extraction failed: {e}")
                
                # Basic fallback - word frequency
                if not topics:
                    words = text.lower().split()
                    # Filter out short words and common stop words
                    stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should'}
                    filtered_words = [w for w in words if len(w) > 3 and w not in stop_words]
                    
                    from collections import Counter
                    if filtered_words:
                        word_counts = Counter(filtered_words)
                        topics = [
                            {"keyword": word, "score": count / len(filtered_words)}
                            for word, count in word_counts.most_common(max_topics)
                        ]
                
                return {
                    "topics": topics,
                    "extraction_method": "keybert" if keybert else ("spacy" if self.get_spacy_model() else "basic"),
                    "text_length": len(text)
                }
                
            except Exception as e:
                logger.error(f"Topic extraction failed: {e}")
                return {"topics": [], "error": str(e)}
        
        return await asyncio.get_event_loop().run_in_executor(None, extract)
    
    async def summarize_text(self, text: str, max_sentences: int = 3) -> str:
        """Generate text summary using TextRank."""
        def summarize():
            try:
                if len(text) < 100:
                    return text

                import re
                from collections import Counter

                sentences = [s.strip() for s in re.split(r'(?<=[.!?]) +', text) if len(s.strip()) > 20]
                if not sentences:
                    return text

                words = re.findall(r"[A-Za-z']+", text.lower())
                stop_words = {
                    'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by',
                    'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did'
                }
                filtered = [w for w in words if len(w) > 3 and w not in stop_words]
                if not filtered:
                    return " ".join(sentences[:max_sentences])

                freq = Counter(filtered)
                sentence_scores = []
                for sentence in sentences:
                    tokens = re.findall(r"[A-Za-z']+", sentence.lower())
                    score = sum(freq.get(token, 0) for token in tokens if token not in stop_words)
                    sentence_scores.append((score, sentence))

                top_sentences = sorted(sentence_scores, key=lambda x: x[0], reverse=True)[:max_sentences]
                ordered = [sentence for _, sentence in sorted(top_sentences, key=lambda x: sentences.index(x[1]))]
                summary = " ".join(ordered)
                return summary if summary else " ".join(sentences[:max_sentences])

            except Exception as e:
                logger.error(f"Text summarization failed: {e}")
                return text[:200] + "..." if len(text) > 200 else text
        
        return await asyncio.get_event_loop().run_in_executor(None, summarize)