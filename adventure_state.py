"""Match checkpoints and bounded personal review, independent of Discord transport."""

import logging
import re
import sqlite3
import uuid
from types import SimpleNamespace

from difficulty import FORMATS, LABELS
from quiz_content import QuestionDeck

log = logging.getLogger('adventures.state')
MAX_PLAYERS = 200
REVIEW_LIMIT = 50


class AdventureState:
    def init_adventure(self, repository=None):
        self.repository = repository
        self.session_id = uuid.uuid4().hex
        self.difficulty = 'all'
        self.answer_mode = 'mixed'
        self.lobby_page = 'main'
        self.performance = {}
        self.review_history = []
        self.round_people = {}
        self.round_winner_id = None
        self.round_complete = False
        self.round_reviewed = False
        self.host_missing = False
        self.suspending = False
        self.persistence_failed = False
        self.dirty = False

    def track_attempt(self, user):
        if user.id not in self.performance and len(self.performance) >= MAX_PLAYERS:
            return False
        entry = self.performance.setdefault(user.id, {'name': user.display_name, 'attempts': 0, 'played': 0, 'won': 0, 'categories': {}})
        entry['name'] = user.display_name
        entry['attempts'] += 1
        person = self.round_people.setdefault(user.id, {'name': user.display_name, 'attempts': 0})
        person['attempts'] += 1
        self.dirty = True
        return True

    def finish_round_review(self, winner_id=None):
        if self.round_reviewed or not self.current_question:
            return
        self.round_reviewed = self.round_complete = True
        for uid in self.round_people:
            entry = self.performance[uid]
            entry['played'] += 1
            entry['won'] += int(uid == winner_id)
            category = entry['categories'].setdefault(self.current_question.category, {'played': 0, 'won': 0})
            category['played'] += 1
            category['won'] += int(uid == winner_id)
        self.review_history.append({'number': self.question_number, 'question_id': self.current_question.id,
                                    'winner_id': winner_id, 'participants': list(self.round_people)})
        self.review_history = self.review_history[-REVIEW_LIMIT:]
        self.dirty = True

    def snapshot(self):
        return {
            'schema': 1, 'id': self.session_id, 'stage': self.pack.stage, 'fingerprint': self.pack.fingerprint,
            'channel_id': self.channel.id, 'guild_id': self.guild_id,
            'host': {'id': self.host.id, 'name': self.host.display_name}, 'host_missing': self.host_missing,
            'settings': {'group': self.group, 'difficulty': self.difficulty, 'format': self.answer_mode,
                         'rounds': self.round_limit, 'time': self.question_time},
            'phase': self.phase, 'question_number': self.question_number, 'correct_count': self.correct_count,
            'stop_requested': self.stop_requested,
            'scores': self.session_scores, 'performance': self.performance, 'reviews': self.review_history,
            'deck': self.deck.snapshot() if self.phase!='lobby' and hasattr(self.deck, 'snapshot') else None,
            'control_message_id': getattr(self.control_message, 'id', None),
            'round': {'question_id': getattr(self.current_question, 'id', None),
                      'message_id': getattr(self.question_message, 'id', None),
                      'complete': self.round_complete, 'reviewed': self.round_reviewed,
                      'winner_recorded': self.winner_recorded, 'winner_id': self.round_winner_id,
                      'people': self.round_people},
        }

    def checkpoint(self, status=None):
        if self.repository is None:
            return
        status = status or ('suspended' if self.suspending else 'finished' if not self.running or self.phase == 'ended'
                            else 'lobby' if self.phase == 'lobby' else 'recovery' if self.phase == 'recovery' else 'active')
        try:
            self.repository.save(self.snapshot(), status)
            self.persistence_failed = self.dirty = False
        except (OSError, sqlite3.Error, ValueError):
            self.persistence_failed = True
            log.exception('Não foi possível salvar a partida %s; pontos usam recibos independentes.', self.session_id)

    def remember_panel(self, *, resolved=False):
        self.checkpoint()
        if self.repository is not None and self.control_message:
            try:
                self.repository.remember_message(self.control_message.id, self.session_id,
                    getattr(self.current_question, 'id', None), resolved=resolved)
            except sqlite3.Error:
                log.exception('Não foi possível registrar o contexto do painel.')

    def load_saved(self, state, groups):
        if (state.get('schema') != 1 or state.get('stage') != self.pack.stage
                or state.get('fingerprint') != self.pack.fingerprint
                or not re.fullmatch('[0-9a-f]{32}', state.get('id', ''))):
            raise ValueError('Essa partida usa um banco de perguntas incompatível.')
        settings = state['settings']
        if (settings['group'] not in groups or settings['difficulty'] not in LABELS
                or settings['format'] not in FORMATS or settings['rounds'] not in (10,20,30,None)
                or settings['time'] not in (30,45,60)):
            raise ValueError('As opções salvas não são válidas.')
        self.session_id = state['id']
        self.group, self.difficulty, self.answer_mode = settings['group'], settings['difficulty'], settings['format']
        self.round_limit, self.question_time = settings['rounds'], settings['time']
        self.guild_id = state['guild_id']
        self.question_number, self.correct_count = int(state['question_number']), int(state['correct_count'])
        self.stop_requested = bool(state.get('stop_requested'))
        if not 0 <= self.correct_count <= self.question_number <= 1000000:
            raise ValueError('Progresso salvo inválido.')
        self.session_scores = {int(k): v for k,v in state['scores'].items()}
        self.performance = {int(k): v for k,v in state['performance'].items()}
        self.review_history = state['reviews'][-REVIEW_LIMIT:]
        if len(self.performance) > MAX_PLAYERS or len(self.session_scores) > MAX_PLAYERS:
            raise ValueError('Participantes salvos acima do limite.')
        self.host_missing = bool(state.get('host_missing'))
        selected = self.selected_questions()
        self.deck = QuestionDeck(selected or self.pack.questions) if state['phase']=='lobby' else QuestionDeck(selected)
        if state.get('deck') is not None:
            self.deck.restore(state['deck'])
        saved_round = state['round']
        self.current_question = next((q for q in self.pack.questions if q.id == saved_round['question_id']), None)
        self.question_message = SimpleNamespace(id=saved_round['message_id']) if saved_round['message_id'] else None
        self.round_complete, self.round_reviewed = saved_round['complete'], saved_round['reviewed']
        self.winner_recorded = bool(saved_round['winner_recorded'])
        self.round_winner_id = saved_round.get('winner_id')
        self.round_people = {int(k):v for k,v in saved_round['people'].items()}
        self.running = True
        self.phase = 'lobby' if state['phase'] == 'lobby' else 'recovery'
        if self.current_question and not self.round_complete:
            award = self.repository.award_for(self.question_message.id) if self.repository and self.question_message else None
            if award:
                if not self.winner_recorded:
                    winner = SimpleNamespace(id=award['user_id'],display_name=award['name'])
                    self.record_winner(winner)
                self.finish_round_review(award['user_id'])
            elif self.winner_recorded:
                self.finish_round_review(self.round_winner_id)
            else:
                # A round without a recorded winner is void; never repeat its old buttons or answers.
                self.question_number = max(0, self.question_number - 1)
                for uid, person in self.round_people.items():
                    if uid in self.performance:
                        self.performance[uid]['attempts'] = max(0,self.performance[uid]['attempts'] - person['attempts'])
                self.round_people = {}
        self.timer = None
