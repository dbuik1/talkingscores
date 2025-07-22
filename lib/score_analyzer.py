"""
Score Analysis Coordination for Talking Scores

This module provides high-level coordination of musical analysis,
bringing together various analysis components and managing the
analysis workflow.
"""

import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from collections import defaultdict, Counter

logger = logging.getLogger("TSScore")


@dataclass
class AnalysisResult:
    """Container for analysis results."""
    success: bool
    data: Dict[str, Any]
    errors: List[str]
    warnings: List[str]
    
    def __post_init__(self):
        """Initialize empty lists if None."""
        if self.errors is None:
            self.errors = []
        if self.warnings is None:
            self.warnings = []
        if self.data is None:
            self.data = {}


class StructuralAnalyzer:
    """
    Analyzes structural elements of a musical score.
    
    This class handles analysis of time signatures, key signatures,
    tempo markings, and other structural elements.
    """
    
    def __init__(self, score):
        self.score = score
    
    def analyze_time_signatures(self) -> AnalysisResult:
        """Analyze time signature changes throughout the score."""
        try:
            time_signatures = []
            changes_by_bar = {}
            
            if not self.score.parts:
                return AnalysisResult(False, {}, ["No parts found in score"], [])
            
            first_part = self.score.parts[0]
            time_sigs = first_part.flatten().getElementsByClass('TimeSignature')
            
            for i, ts in enumerate(time_sigs):
                ts_info = {
                    'index': i,
                    'numerator': ts.numerator,
                    'denominator': ts.denominator,
                    'ratio_string': ts.ratioString,
                    'measure_number': getattr(ts, 'measureNumber', None),
                    'offset': getattr(ts, 'offset', 0.0)
                }
                time_signatures.append(ts_info)
                
                if ts_info['measure_number']:
                    changes_by_bar[ts_info['measure_number']] = ts_info
            
            analysis_data = {
                'time_signatures': time_signatures,
                'changes_by_bar': changes_by_bar,
                'total_changes': len(time_signatures) - 1 if time_signatures else 0,
                'has_changes': len(time_signatures) > 1
            }
            
            return AnalysisResult(True, analysis_data, [], [])
            
        except Exception as e:
            logger.error(f"Error analyzing time signatures: {e}")
            return AnalysisResult(False, {}, [str(e)], [])
    
    def analyze_key_signatures(self) -> AnalysisResult:
        """Analyze key signature changes throughout the score."""
        try:
            key_signatures = []
            changes_by_bar = {}
            
            if not self.score.parts:
                return AnalysisResult(False, {}, ["No parts found in score"], [])
            
            first_part = self.score.parts[0]
            key_sigs = first_part.flatten().getElementsByClass('KeySignature')
            
            for i, ks in enumerate(key_sigs):
                ks_info = {
                    'index': i,
                    'sharps': ks.sharps,
                    'key_name': str(ks) if hasattr(ks, '__str__') else 'Unknown',
                    'measure_number': getattr(ks, 'measureNumber', None),
                    'offset': getattr(ks, 'offset', 0.0)
                }
                key_signatures.append(ks_info)
                
                if ks_info['measure_number']:
                    changes_by_bar[ks_info['measure_number']] = ks_info
            
            analysis_data = {
                'key_signatures': key_signatures,
                'changes_by_bar': changes_by_bar,
                'total_changes': len(key_signatures) - 1 if key_signatures else 0,
                'has_changes': len(key_signatures) > 1
            }
            
            return AnalysisResult(True, analysis_data, [], [])
            
        except Exception as e:
            logger.error(f"Error analyzing key signatures: {e}")
            return AnalysisResult(False, {}, [str(e)], [])
    
    def analyze_tempo_markings(self) -> AnalysisResult:
        """Analyze tempo markings throughout the score."""
        try:
            tempo_markings = []
            changes_by_bar = {}
            
            tempos = self.score.flatten().getElementsByClass('MetronomeMark')
            
            for i, tempo in enumerate(tempos):
                tempo_info = {
                    'index': i,
                    'number': getattr(tempo, 'number', None),
                    'text': getattr(tempo, 'text', None),
                    'referent': str(getattr(tempo, 'referent', 'quarter')),
                    'measure_number': getattr(tempo, 'measureNumber', None),
                    'offset': getattr(tempo, 'offset', 0.0)
                }
                tempo_markings.append(tempo_info)
                
                if tempo_info['measure_number']:
                    changes_by_bar[tempo_info['measure_number']] = tempo_info
            
            analysis_data = {
                'tempo_markings': tempo_markings,
                'changes_by_bar': changes_by_bar,
                'total_changes': len(tempo_markings) - 1 if tempo_markings else 0,
                'has_changes': len(tempo_markings) > 1
            }
            
            return AnalysisResult(True, analysis_data, [], [])
            
        except Exception as e:
            logger.error(f"Error analyzing tempo markings: {e}")
            return AnalysisResult(False, {}, [str(e)], [])


class RhythmAnalyzer:
    """
    Analyzes rhythmic content and patterns in a musical score.
    
    This class identifies rhythm patterns, duration distributions,
    and rhythmic complexity metrics.
    """
    
    def __init__(self, score):
        self.score = score
    
    def analyze_rhythm_patterns(self) -> AnalysisResult:
        """Analyze rhythm patterns across all parts."""
        try:
            all_durations = []
            duration_counts = Counter()
            part_rhythms = {}
            
            for part_index, part in enumerate(self.score.parts):
                part_durations = []
                
                for element in part.flatten().notesAndRests:
                    if hasattr(element, 'duration'):
                        duration_ql = element.duration.quarterLength
                        duration_type = getattr(element.duration, 'type', 'unknown')
                        
                        duration_info = {
                            'quarter_length': duration_ql,
                            'type': duration_type,
                            'dots': getattr(element.duration, 'dots', 0),
                            'is_rest': element.isRest,
                            'measure_number': getattr(element, 'measureNumber', None)
                        }
                        
                        part_durations.append(duration_info)
                        all_durations.append(duration_info)
                        duration_counts[duration_ql] += 1
                
                part_rhythms[part_index] = part_durations
            
            # Find most common rhythms
            common_rhythms = duration_counts.most_common(10)
            
            # Calculate rhythmic diversity
            total_notes = len(all_durations)
            unique_rhythms = len(duration_counts)
            rhythmic_diversity = unique_rhythms / total_notes if total_notes > 0 else 0
            
            analysis_data = {
                'all_durations': all_durations,
                'duration_counts': dict(duration_counts),
                'part_rhythms': part_rhythms,
                'common_rhythms': common_rhythms,
                'rhythmic_diversity': rhythmic_diversity,
                'total_note_count': total_notes,
                'unique_rhythm_count': unique_rhythms
            }
            
            return AnalysisResult(True, analysis_data, [], [])
            
        except Exception as e:
            logger.error(f"Error analyzing rhythm patterns: {e}")
            return AnalysisResult(False, {}, [str(e)], [])
    
    def analyze_meter_and_beat_patterns(self) -> AnalysisResult:
        """Analyze meter and beat-level patterns."""
        try:
            beat_patterns = {}
            syncopation_events = []
            
            for part_index, part in enumerate(self.score.parts):
                part_beat_patterns = []
                
                for measure in part.getElementsByClass('Measure'):
                    measure_pattern = self._analyze_measure_beats(measure)
                    if measure_pattern:
                        part_beat_patterns.append(measure_pattern)
                
                beat_patterns[part_index] = part_beat_patterns
            
            analysis_data = {
                'beat_patterns': beat_patterns,
                'syncopation_events': syncopation_events
            }
            
            return AnalysisResult(True, analysis_data, [], [])
            
        except Exception as e:
            logger.error(f"Error analyzing meter and beat patterns: {e}")
            return AnalysisResult(False, {}, [str(e)], [])
    
    def _analyze_measure_beats(self, measure) -> Optional[Dict[str, Any]]:
        """Analyze beat patterns within a single measure."""
        try:
            time_sig = measure.timeSignature or measure.previous('TimeSignature')
            if not time_sig:
                return None
            
            beat_events = []
            for element in measure.notesAndRests:
                if hasattr(element, 'beat'):
                    beat_info = {
                        'beat': element.beat,
                        'duration': element.duration.quarterLength,
                        'is_rest': element.isRest,
                        'is_syncopated': self._is_syncopated(element, time_sig)
                    }
                    beat_events.append(beat_info)
            
            return {
                'measure_number': measure.number,
                'time_signature': time_sig.ratioString,
                'beat_events': beat_events
            }
            
        except Exception as e:
            logger.warning(f"Error analyzing beats in measure: {e}")
            return None
    
    def _is_syncopated(self, element, time_signature) -> bool:
        """Determine if an element represents syncopation."""
        # Simplified syncopation detection
        # This could be enhanced with more sophisticated analysis
        try:
            beat = getattr(element, 'beat', 1.0)
            duration = element.duration.quarterLength
            
            # Basic heuristic: notes starting off strong beats with certain durations
            beat_strength = time_signature.getBeatStrength(beat)
            return beat_strength < 0.5 and duration >= 0.5
        except:
            return False


class PitchAnalyzer:
    """
    Analyzes pitch content and relationships in a musical score.
    
    This class handles pitch distributions, interval analysis,
    range analysis, and tonal characteristics.
    """
    
    def __init__(self, score):
        self.score = score
    
    def analyze_pitch_content(self) -> AnalysisResult:
        """Analyze pitch usage across all parts."""
        try:
            all_pitches = []
            pitch_counts = Counter()
            pitch_class_counts = Counter()
            part_pitches = {}
            
            for part_index, part in enumerate(self.score.parts):
                part_pitch_data = []
                
                for element in part.flatten().notes:
                    pitches_to_analyze = []
                    
                    if hasattr(element, 'pitches'):  # Chord
                        pitches_to_analyze = element.pitches
                    elif hasattr(element, 'pitch'):  # Single note
                        pitches_to_analyze = [element.pitch]
                    
                    for pitch in pitches_to_analyze:
                        pitch_info = {
                            'midi_number': pitch.midi,
                            'name': pitch.name,
                            'octave': pitch.octave,
                            'pitch_class': pitch.pitchClass,
                            'frequency': pitch.frequency,
                            'measure_number': getattr(element, 'measureNumber', None)
                        }
                        
                        part_pitch_data.append(pitch_info)
                        all_pitches.append(pitch_info)
                        pitch_counts[pitch.midi] += 1
                        pitch_class_counts[pitch.pitchClass] += 1
                
                part_pitches[part_index] = part_pitch_data
            
            # Calculate ranges
            if all_pitches:
                midi_numbers = [p['midi_number'] for p in all_pitches]
                pitch_range = {
                    'lowest_midi': min(midi_numbers),
                    'highest_midi': max(midi_numbers),
                    'range_semitones': max(midi_numbers) - min(midi_numbers)
                }
                
                octaves = [p['octave'] for p in all_pitches]
                octave_range = {
                    'lowest_octave': min(octaves),
                    'highest_octave': max(octaves)
                }
            else:
                pitch_range = {'lowest_midi': 0, 'highest_midi': 0, 'range_semitones': 0}
                octave_range = {'lowest_octave': 0, 'highest_octave': 0}
            
            analysis_data = {
                'all_pitches': all_pitches,
                'pitch_counts': dict(pitch_counts),
                'pitch_class_counts': dict(pitch_class_counts),
                'part_pitches': part_pitches,
                'pitch_range': pitch_range,
                'octave_range': octave_range,
                'total_pitch_events': len(all_pitches),
                'unique_pitches': len(pitch_counts),
                'unique_pitch_classes': len(pitch_class_counts)
            }
            
            return AnalysisResult(True, analysis_data, [], [])
            
        except Exception as e:
            logger.error(f"Error analyzing pitch content: {e}")
            return AnalysisResult(False, {}, [str(e)], [])
    
    def analyze_intervals(self) -> AnalysisResult:
        """Analyze melodic intervals in all parts."""
        try:
            all_intervals = []
            interval_counts = Counter()
            part_intervals = {}
            
            for part_index, part in enumerate(self.score.parts):
                part_interval_data = []
                previous_pitch = None
                
                for element in part.flatten().notes:
                    if hasattr(element, 'pitch'):  # Single notes only
                        current_pitch = element.pitch
                        
                        if previous_pitch is not None:
                            try:
                                interval_obj = interval.Interval(previous_pitch, current_pitch)
                                interval_info = {
                                    'semitones': interval_obj.semitones,
                                    'name': interval_obj.name,
                                    'direction': interval_obj.direction.name,
                                    'is_ascending': interval_obj.semitones > 0,
                                    'measure_number': getattr(element, 'measureNumber', None)
                                }
                                
                                part_interval_data.append(interval_info)
                                all_intervals.append(interval_info)
                                interval_counts[interval_obj.semitones] += 1
                                
                            except Exception as e:
                                logger.warning(f"Error calculating interval: {e}")
                        
                        previous_pitch = current_pitch
                
                part_intervals[part_index] = part_interval_data
            
            # Calculate interval statistics
            if all_intervals:
                ascending_count = sum(1 for i in all_intervals if i['is_ascending'])
                descending_count = len(all_intervals) - ascending_count
                
                interval_stats = {
                    'total_intervals': len(all_intervals),
                    'ascending_count': ascending_count,
                    'descending_count': descending_count,
                    'ascending_percentage': ascending_count / len(all_intervals) * 100,
                    'most_common_intervals': interval_counts.most_common(10)
                }
            else:
                interval_stats = {
                    'total_intervals': 0,
                    'ascending_count': 0,
                    'descending_count': 0,
                    'ascending_percentage': 0,
                    'most_common_intervals': []
                }
            
            analysis_data = {
                'all_intervals': all_intervals,
                'interval_counts': dict(interval_counts),
                'part_intervals': part_intervals,
                'interval_statistics': interval_stats
            }
            
            return AnalysisResult(True, analysis_data, [], [])
            
        except Exception as e:
            logger.error(f"Error analyzing intervals: {e}")
            return AnalysisResult(False, {}, [str(e)], [])


class ScoreAnalyzer:
    """
    Main score analyzer that coordinates all analysis components.
    
    This class provides a unified interface for analyzing musical scores
    and combines results from various specialized analyzers.
    """
    
    def __init__(self, score):
        """
        Initialize with a music21 score.
        
        Args:
            score: music21.stream.Score object
        """
        self.score = score
        
        # Initialize specialized analyzers
        self.structural_analyzer = StructuralAnalyzer(score)
        self.rhythm_analyzer = RhythmAnalyzer(score)
        self.pitch_analyzer = PitchAnalyzer(score)
    
    def analyze_full_score(self) -> AnalysisResult:
        """
        Perform comprehensive analysis of the entire score.
        
        Returns:
            AnalysisResult containing all analysis data
        """
        try:
            all_data = {}
            all_errors = []
            all_warnings = []
            
            # Structural analysis
            logger.debug("Performing structural analysis...")
            structural_results = self._run_structural_analysis()
            all_data['structural'] = structural_results.data
            all_errors.extend(structural_results.errors)
            all_warnings.extend(structural_results.warnings)
            
            # Rhythmic analysis
            logger.debug("Performing rhythmic analysis...")
            rhythm_results = self._run_rhythm_analysis()
            all_data['rhythm'] = rhythm_results.data
            all_errors.extend(rhythm_results.errors)
            all_warnings.extend(rhythm_results.warnings)
            
            # Pitch analysis
            logger.debug("Performing pitch analysis...")
            pitch_results = self._run_pitch_analysis()
            all_data['pitch'] = pitch_results.data
            all_errors.extend(pitch_results.errors)
            all_warnings.extend(pitch_results.warnings)
            
            # Compute summary statistics
            all_data['summary'] = self._compute_summary_statistics(all_data)
            
            success = len(all_errors) == 0
            return AnalysisResult(success, all_data, all_errors, all_warnings)
            
        except Exception as e:
            logger.error(f"Error in full score analysis: {e}")
            return AnalysisResult(False, {}, [str(e)], [])
    
    def _run_structural_analysis(self) -> AnalysisResult:
        """Run all structural analysis components."""
        try:
            combined_data = {}
            combined_errors = []
            combined_warnings = []
            
            # Time signatures
            ts_result = self.structural_analyzer.analyze_time_signatures()
            combined_data['time_signatures'] = ts_result.data
            combined_errors.extend(ts_result.errors)
            combined_warnings.extend(ts_result.warnings)
            
            # Key signatures
            ks_result = self.structural_analyzer.analyze_key_signatures()
            combined_data['key_signatures'] = ks_result.data
            combined_errors.extend(ks_result.errors)
            combined_warnings.extend(ks_result.warnings)
            
            # Tempo markings
            tempo_result = self.structural_analyzer.analyze_tempo_markings()
            combined_data['tempo_markings'] = tempo_result.data
            combined_errors.extend(tempo_result.errors)
            combined_warnings.extend(tempo_result.warnings)
            
            success = len(combined_errors) == 0
            return AnalysisResult(success, combined_data, combined_errors, combined_warnings)
            
        except Exception as e:
            return AnalysisResult(False, {}, [str(e)], [])
    
    def _run_rhythm_analysis(self) -> AnalysisResult:
        """Run all rhythmic analysis components."""
        try:
            combined_data = {}
            combined_errors = []
            combined_warnings = []
            
            # Rhythm patterns
            rhythm_result = self.rhythm_analyzer.analyze_rhythm_patterns()
            combined_data['patterns'] = rhythm_result.data
            combined_errors.extend(rhythm_result.errors)
            combined_warnings.extend(rhythm_result.warnings)
            
            # Beat analysis
            beat_result = self.rhythm_analyzer.analyze_meter_and_beat_patterns()
            combined_data['beats'] = beat_result.data
            combined_errors.extend(beat_result.errors)
            combined_warnings.extend(beat_result.warnings)
            
            success = len(combined_errors) == 0
            return AnalysisResult(success, combined_data, combined_errors, combined_warnings)
            
        except Exception as e:
            return AnalysisResult(False, {}, [str(e)], [])
    
    def _run_pitch_analysis(self) -> AnalysisResult:
        """Run all pitch analysis components."""
        try:
            combined_data = {}
            combined_errors = []
            combined_warnings = []
            
            # Pitch content
            pitch_result = self.pitch_analyzer.analyze_pitch_content()
            combined_data['content'] = pitch_result.data
            combined_errors.extend(pitch_result.errors)
            combined_warnings.extend(pitch_result.warnings)
            
            # Intervals
            interval_result = self.pitch_analyzer.analyze_intervals()
            combined_data['intervals'] = interval_result.data
            combined_errors.extend(interval_result.errors)
            combined_warnings.extend(interval_result.warnings)
            
            success = len(combined_errors) == 0
            return AnalysisResult(success, combined_data, combined_errors, combined_warnings)
            
        except Exception as e:
            return AnalysisResult(False, {}, [str(e)], [])
    
    def _compute_summary_statistics(self, all_data: Dict[str, Any]) -> Dict[str, Any]:
        """Compute high-level summary statistics."""
        try:
            summary = {}
            
            # Basic score information
            summary['total_parts'] = len(self.score.parts)
            summary['total_measures'] = len(self.score.parts[0].getElementsByClass('Measure')) if self.score.parts else 0
            
            # Rhythm summary
            rhythm_data = all_data.get('rhythm', {}).get('patterns', {})
            summary['total_note_events'] = rhythm_data.get('total_note_count', 0)
            summary['rhythmic_diversity'] = rhythm_data.get('rhythmic_diversity', 0)
            
            # Pitch summary
            pitch_data = all_data.get('pitch', {}).get('content', {})
            summary['total_pitch_events'] = pitch_data.get('total_pitch_events', 0)
            summary['pitch_range_semitones'] = pitch_data.get('pitch_range', {}).get('range_semitones', 0)
            summary['unique_pitches'] = pitch_data.get('unique_pitches', 0)
            
            # Interval summary
            interval_data = all_data.get('pitch', {}).get('intervals', {})
            interval_stats = interval_data.get('interval_statistics', {})
            summary['total_intervals'] = interval_stats.get('total_intervals', 0)
            summary['ascending_percentage'] = interval_stats.get('ascending_percentage', 0)
            
            # Structural summary
            structural_data = all_data.get('structural', {})
            ts_data = structural_data.get('time_signatures', {})
            ks_data = structural_data.get('key_signatures', {})
            tempo_data = structural_data.get('tempo_markings', {})
            
            summary['time_signature_changes'] = ts_data.get('total_changes', 0)
            summary['key_signature_changes'] = ks_data.get('total_changes', 0)
            summary['tempo_changes'] = tempo_data.get('total_changes', 0)
            
            return summary
            
        except Exception as e:
            logger.error(f"Error computing summary statistics: {e}")
            return {}
    
    def analyze_segment(self, start_bar: int, end_bar: int) -> AnalysisResult:
        """
        Analyze a specific segment of the score.
        
        Args:
            start_bar: Starting measure number
            end_bar: Ending measure number
            
        Returns:
            AnalysisResult for the specified segment
        """
        try:
            # Extract the segment
            segment_score = self._extract_score_segment(start_bar, end_bar)
            
            # Create a temporary analyzer for the segment
            segment_analyzer = ScoreAnalyzer(segment_score)
            
            # Analyze the segment
            return segment_analyzer.analyze_full_score()
            
        except Exception as e:
            logger.error(f"Error analyzing segment {start_bar}-{end_bar}: {e}")
            return AnalysisResult(False, {}, [str(e)], [])
    
    def _extract_score_segment(self, start_bar: int, end_bar: int):
        """Extract a segment of the score for analysis."""
        from music21 import stream
        
        segment = stream.Score()
        
        for part in self.score.parts:
            part_segment = part.measures(start_bar, end_bar)
            if part_segment:
                segment.append(part_segment)
        
        return segment
    
    def get_analysis_summary(self) -> str:
        """
        Get a human-readable summary of the analysis.
        
        Returns:
            Text summary of the analysis results
        """
        try:
            full_analysis = self.analyze_full_score()
            
            if not full_analysis.success:
                return f"Analysis failed: {'; '.join(full_analysis.errors)}"
            
            summary_data = full_analysis.data.get('summary', {})
            
            summary_lines = [
                f"Score Analysis Summary:",
                f"- {summary_data.get('total_parts', 0)} parts",
                f"- {summary_data.get('total_measures', 0)} measures", 
                f"- {summary_data.get('total_note_events', 0)} note events",
                f"- {summary_data.get('total_pitch_events', 0)} pitch events",
                f"- {summary_data.get('pitch_range_semitones', 0)} semitone range",
                f"- {summary_data.get('rhythmic_diversity', 0):.2f} rhythmic diversity",
                f"- {summary_data.get('time_signature_changes', 0)} time signature changes",
                f"- {summary_data.get('key_signature_changes', 0)} key signature changes",
                f"- {summary_data.get('tempo_changes', 0)} tempo changes"
            ]
            
            if full_analysis.warnings:
                summary_lines.append(f"Warnings: {'; '.join(full_analysis.warnings)}")
            
            return '\n'.join(summary_lines)
            
        except Exception as e:
            return f"Error generating analysis summary: {e}"