import json
import re
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_

db = SQLAlchemy()
SUMMARY_META_PATTERN = re.compile(r"^\s*<!--PF_SUMMARY_META:(\{.*?\})-->\s*", re.DOTALL)


def _decode_summary_payload(summary_value):
    if not summary_value:
        return summary_value, None
    text = str(summary_value)
    match = SUMMARY_META_PATTERN.match(text)
    if not match:
        return text, None

    source = None
    try:
        meta = json.loads(match.group(1))
        source = meta.get("source")
    except Exception:
        source = None

    clean = text[match.end():].lstrip()
    return clean, source


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(80), nullable=True)
    avatar_url = db.Column(db.String(500), nullable=True)
    profile_bio = db.Column(db.Text, nullable=True)
    profile_research_areas_json = db.Column(db.Text, nullable=True)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # relationships
    user_papers = db.relationship("UserPaper", back_populates="user", lazy="dynamic")
    preference = db.relationship(
        "UserPreference",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def profile_research_areas(self):
        if not self.profile_research_areas_json:
            return []
        try:
            data = json.loads(self.profile_research_areas_json)
            if isinstance(data, list):
                return [str(x).strip() for x in data if str(x).strip()]
        except Exception:
            return []
        return []

    @profile_research_areas.setter
    def profile_research_areas(self, value):
        if not isinstance(value, list):
            value = []
        cleaned = [str(x).strip() for x in value if str(x).strip()]
        self.profile_research_areas_json = json.dumps(cleaned, ensure_ascii=False)

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "display_name": self.display_name,
            "avatar_url": self.avatar_url,
            "profile_bio": self.profile_bio,
            "profile_research_areas": self.profile_research_areas,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Paper(db.Model):
    __tablename__ = "papers"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    article_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    title = db.Column(db.String(500), nullable=True)
    title_zh = db.Column(db.String(500), nullable=True)  # Chinese translation of title
    authors_json = db.Column(db.Text, nullable=True)  # JSON list of author names
    affiliations_json = db.Column(db.Text, nullable=True)  # JSON list of affiliations
    abstract = db.Column(db.Text, nullable=True)
    publication_date = db.Column(db.String(100), nullable=True)
    publication_title = db.Column(db.String(300), nullable=True)
    download_count = db.Column(db.Integer, default=0)
    pdf_path = db.Column(db.String(500), nullable=True)
    summary = db.Column(db.Text, nullable=True)
    summary_generated_at = db.Column(db.DateTime, nullable=True)
    keywords_json = db.Column(db.Text, nullable=True)   # JSON list of 3-4 keywords
    category = db.Column(db.String(100), nullable=True, index=True)  # e.g. "大模型", "强化学习"
    source_url = db.Column(db.String(500), nullable=True)  # link to original paper page
    figure_path = db.Column(db.String(500), nullable=True)  # path to first figure image
    figure_explanation = db.Column(db.Text, nullable=True)  # AI explanation of the figure
    # user_upload / system
    content_origin = db.Column(db.String(30), nullable=True, default="system", index=True)
    created_by_user_id = db.Column(db.Integer, nullable=True, index=True)
    # pending / processing / ready / failed
    processing_status = db.Column(db.String(20), nullable=True, default="ready", index=True)
    processing_error = db.Column(db.Text, nullable=True)
    # pending / approved / rejected
    creator_review_status = db.Column(db.String(20), nullable=True, default="approved", index=True)
    creator_review_note = db.Column(db.Text, nullable=True)
    creator_reviewed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    creator_reviewed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # relationships
    user_papers = db.relationship("UserPaper", back_populates="paper", lazy="dynamic")
    recommendations = db.relationship("Recommendation", back_populates="paper", lazy="dynamic")
    ratings = db.relationship("PaperRating", back_populates="paper", lazy="dynamic")
    comments = db.relationship("PaperComment", back_populates="paper", lazy="dynamic")
    creator_reviewer = db.relationship("User", foreign_keys=[creator_reviewed_by])

    @staticmethod
    def is_public_clause():
        return or_(
            Paper.content_origin.is_(None),
            Paper.content_origin != "user_upload",
            Paper.creator_review_status == "approved",
        )

    @property
    def authors(self):
        if self.authors_json:
            return json.loads(self.authors_json)
        return []

    @authors.setter
    def authors(self, value):
        self.authors_json = json.dumps(value, ensure_ascii=False)

    @property
    def keywords(self):
        if self.keywords_json:
            return json.loads(self.keywords_json)
        return []

    @keywords.setter
    def keywords(self, value):
        self.keywords_json = json.dumps(value, ensure_ascii=False)

    def avg_rating(self):
        ratings = PaperRating.query.filter_by(paper_id=self.id).all()
        if not ratings:
            return None
        return round(sum(r.score for r in ratings) / len(ratings), 1)

    def rating_count(self):
        return PaperRating.query.filter_by(paper_id=self.id).count()

    @property
    def affiliations(self):
        if self.affiliations_json:
            return json.loads(self.affiliations_json)
        return []

    @affiliations.setter
    def affiliations(self, value):
        self.affiliations_json = json.dumps(value, ensure_ascii=False)

    def _infer_url(self):
        """Build URL from article_number when source_url is not stored."""
        arn = self.article_number or ''
        if arn.startswith('arxiv_'):
            return f"https://arxiv.org/abs/{arn[6:]}"
        if arn.startswith('elsevier_'):
            doi = arn[9:].replace('_', '/')
            return f"https://doi.org/{doi}"
        if arn.startswith('crossref_'):
            import re
            doi_raw = arn[9:]
            m = re.match(r'(10\.\d{4,9})_(.*)', doi_raw)
            if m:
                return f"https://doi.org/{m.group(1)}/{m.group(2)}"
        # IEEE
        if arn.isdigit():
            return f"https://ieeexplore.ieee.org/document/{arn}"
        return None

    def to_dict(self, include_summary=True):
        d = {
            "id": self.id,
            "articleNumber": self.article_number,
            "title": self.title,
            "titleZh": self.title_zh,
            "authors": self.authors,
            "affiliations": self.affiliations,
            "abstract": self.abstract,
            "publicationDate": self.publication_date,
            "publicationTitle": self.publication_title,
            "downloadCount": self.download_count,
            "pdfPath": self.pdf_path,
            "keywords": self.keywords,
            "category": self.category,
            "sourceUrl": self.source_url or self._infer_url(),
            "figurePath": self.figure_path,
            "figureExplanation": self.figure_explanation,
            "contentOrigin": self.content_origin or "system",
            "isUserUploaded": (self.content_origin or "system") == "user_upload",
            "createdByUserId": self.created_by_user_id,
            "processingStatus": self.processing_status or "ready",
            "processingError": self.processing_error,
            "creatorReviewStatus": self.creator_review_status or "approved",
            "creatorReviewNote": self.creator_review_note,
            "creatorReviewedBy": self.creator_reviewed_by,
            "creatorReviewerName": (
                self.creator_reviewer.username if self.creator_reviewer else None
            ),
            "creatorReviewedAt": (
                self.creator_reviewed_at.isoformat() if self.creator_reviewed_at else None
            ),
            "avgRating": self.avg_rating(),
            "ratingCount": self.rating_count(),
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }
        if include_summary:
            clean_summary, summary_source = _decode_summary_payload(self.summary)
            d["summary"] = clean_summary
            d["summarySource"] = summary_source
            d["summaryGeneratedAt"] = (
                self.summary_generated_at.isoformat() if self.summary_generated_at else None
            )
        return d


class UserPaper(db.Model):
    __tablename__ = "user_papers"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    paper_id = db.Column(db.Integer, db.ForeignKey("papers.id"), nullable=False, index=True)
    added_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    notes = db.Column(db.Text, nullable=True)
    is_favorite = db.Column(db.Boolean, default=False)

    __table_args__ = (db.UniqueConstraint("user_id", "paper_id", name="uq_user_paper"),)

    user = db.relationship("User", back_populates="user_papers")
    paper = db.relationship("Paper", back_populates="user_papers")

    def to_dict(self):
        d = self.paper.to_dict()
        d["userPaperId"] = self.id
        d["addedAt"] = self.added_at.isoformat() if self.added_at else None
        d["notes"] = self.notes
        d["isFavorite"] = self.is_favorite
        return d


class UserChannelSubscription(db.Model):
    __tablename__ = "user_channel_subscriptions"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    channel_key = db.Column(db.String(80), nullable=False, index=True)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (db.UniqueConstraint("user_id", "channel_key", name="uq_user_channel_subscription"),)

    user = db.relationship("User", backref="channel_subscriptions")

    def to_dict(self):
        return {
            "id": self.id,
            "userId": self.user_id,
            "channelKey": self.channel_key,
            "enabled": bool(self.enabled),
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }


class ChannelMonitorRecord(db.Model):
    """Per-channel first-seen tracking for monitored papers."""
    __tablename__ = "channel_monitor_records"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    channel_key = db.Column(db.String(80), nullable=False, index=True)
    article_number = db.Column(db.String(80), nullable=False, index=True)
    paper_id = db.Column(db.Integer, db.ForeignKey("papers.id"), nullable=True, index=True)
    first_seen_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    last_seen_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        index=True,
    )

    __table_args__ = (
        db.UniqueConstraint("channel_key", "article_number", name="uq_channel_article_seen"),
    )

    paper = db.relationship("Paper")

    def to_dict(self):
        return {
            "id": self.id,
            "channelKey": self.channel_key,
            "articleNumber": self.article_number,
            "paperId": self.paper_id,
            "firstSeenAt": self.first_seen_at.isoformat() if self.first_seen_at else None,
            "lastSeenAt": self.last_seen_at.isoformat() if self.last_seen_at else None,
            "paper": self.paper.to_dict(include_summary=False) if self.paper else None,
        }


class UserChannelRequest(db.Model):
    __tablename__ = "user_channel_requests"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    detail = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)  # pending/approved/rejected
    admin_note = db.Column(db.String(500), nullable=True)
    reviewed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    user = db.relationship("User", foreign_keys=[user_id], backref="channel_requests")
    reviewer = db.relationship("User", foreign_keys=[reviewed_by])

    def to_dict(self):
        return {
            "id": self.id,
            "userId": self.user_id,
            "username": self.user.username if self.user else None,
            "title": self.title,
            "detail": self.detail,
            "status": self.status,
            "adminNote": self.admin_note,
            "reviewedBy": self.reviewed_by,
            "reviewerName": self.reviewer.username if self.reviewer else None,
            "reviewedAt": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


class PaperEditRequest(db.Model):
    """User-submitted paper card correction request, reviewed by admins."""
    __tablename__ = "paper_edit_requests"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    paper_id = db.Column(db.Integer, db.ForeignKey("papers.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    reason = db.Column(db.Text, nullable=True)
    request_type = db.Column(db.String(30), nullable=False, default="mixed")  # summary/figure/mixed
    target_field = db.Column(db.String(40), nullable=True)  # summary/figureExplanation/figurePath
    selected_text = db.Column(db.Text, nullable=True)
    suggestion_text = db.Column(db.Text, nullable=True)

    # Snapshot before edit request (for transparent history)
    original_summary = db.Column(db.Text, nullable=True)
    original_figure_explanation = db.Column(db.Text, nullable=True)
    original_figure_path = db.Column(db.String(500), nullable=True)

    # Proposed content by user
    proposed_summary = db.Column(db.Text, nullable=True)
    proposed_figure_explanation = db.Column(db.Text, nullable=True)
    proposed_figure_path = db.Column(db.String(500), nullable=True)

    status = db.Column(db.String(20), nullable=False, default="pending", index=True)  # pending/approved/rejected
    admin_note = db.Column(db.String(500), nullable=True)
    reviewed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    paper = db.relationship("Paper", backref="edit_requests")
    requester = db.relationship("User", foreign_keys=[user_id], backref="paper_edit_requests")
    reviewer = db.relationship("User", foreign_keys=[reviewed_by])

    def to_dict(self):
        return {
            "id": self.id,
            "paperId": self.paper_id,
            "articleNumber": self.paper.article_number if self.paper else None,
            "paperTitle": self.paper.title if self.paper else None,
            "userId": self.user_id,
            "username": self.requester.username if self.requester else None,
            "displayName": (self.requester.display_name if self.requester else None) or (
                self.requester.username if self.requester else None
            ),
            "reason": self.reason,
            "requestType": self.request_type,
            "targetField": self.target_field,
            "selectedText": self.selected_text,
            "suggestionText": self.suggestion_text,
            "status": self.status,
            "adminNote": self.admin_note,
            "reviewedBy": self.reviewed_by,
            "reviewerName": self.reviewer.username if self.reviewer else None,
            "reviewedAt": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
            "changes": {
                "summary": {
                    "from": self.original_summary,
                    "to": self.proposed_summary,
                },
                "figureExplanation": {
                    "from": self.original_figure_explanation,
                    "to": self.proposed_figure_explanation,
                },
                "figurePath": {
                    "from": self.original_figure_path,
                    "to": self.proposed_figure_path,
                },
            },
        }


class Recommendation(db.Model):
    __tablename__ = "recommendations"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    paper_id = db.Column(db.Integer, db.ForeignKey("papers.id"), nullable=False, index=True)
    recommended_date = db.Column(db.Date, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    paper = db.relationship("Paper", back_populates="recommendations")

    def to_dict(self):
        d = self.paper.to_dict()
        d["recommendationId"] = self.id
        d["recommendedDate"] = self.recommended_date.isoformat()
        return d


class PaperRating(db.Model):
    __tablename__ = "paper_ratings"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    paper_id = db.Column(db.Integer, db.ForeignKey("papers.id"), nullable=False, index=True)
    score = db.Column(db.Integer, nullable=False)  # 1-5
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (db.UniqueConstraint("user_id", "paper_id", name="uq_user_paper_rating"),)

    user = db.relationship("User")
    paper = db.relationship("Paper", back_populates="ratings")

    def to_dict(self):
        return {
            "id": self.id,
            "userId": self.user_id,
            "paperId": self.paper_id,
            "score": self.score,
        }


class PaperComment(db.Model):
    """User comment for a paper. Supports nested replies via parent_id."""
    __tablename__ = "paper_comments"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    paper_id = db.Column(db.Integer, db.ForeignKey("papers.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("paper_comments.id"), nullable=True, index=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    paper = db.relationship("Paper", back_populates="comments")
    author = db.relationship("User", backref="paper_comments")
    parent = db.relationship(
        "PaperComment",
        remote_side=[id],
        backref=db.backref("replies", lazy="dynamic"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "paperId": self.paper_id,
            "userId": self.user_id,
            "parentId": self.parent_id,
            "content": self.content,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }


class PaperCommentLike(db.Model):
    """Like on a paper comment."""
    __tablename__ = "paper_comment_likes"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    comment_id = db.Column(db.Integer, db.ForeignKey("paper_comments.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    __table_args__ = (db.UniqueConstraint("comment_id", "user_id", name="uq_paper_comment_like"),)

    comment = db.relationship("PaperComment", backref="likes")
    user = db.relationship("User", backref="paper_comment_likes")

    def to_dict(self):
        return {
            "id": self.id,
            "commentId": self.comment_id,
            "userId": self.user_id,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


class Friendship(db.Model):
    """Friend relationship: user_id sends request to friend_id."""
    __tablename__ = "friendships"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    friend_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="pending")  # pending / accepted / rejected
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (db.UniqueConstraint("user_id", "friend_id", name="uq_friendship"),)

    requester = db.relationship("User", foreign_keys=[user_id], backref="sent_requests")
    receiver = db.relationship("User", foreign_keys=[friend_id], backref="received_requests")

    def to_dict(self):
        return {
            "id": self.id,
            "userId": self.user_id,
            "friendId": self.friend_id,
            "status": self.status,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "requester": self.requester.to_dict() if self.requester else None,
            "receiver": self.receiver.to_dict() if self.receiver else None,
        }


class PaperShare(db.Model):
    """A user shares/recommends a paper to a friend."""
    __tablename__ = "paper_shares"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    from_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    to_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    paper_id = db.Column(db.Integer, db.ForeignKey("papers.id"), nullable=False, index=True)
    message = db.Column(db.String(500), nullable=True)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    sender = db.relationship("User", foreign_keys=[from_user_id], backref="shares_sent")
    recipient = db.relationship("User", foreign_keys=[to_user_id], backref="shares_received")
    paper = db.relationship("Paper", backref="shares")

    def to_dict(self):
        return {
            "id": self.id,
            "fromUser": self.sender.to_dict() if self.sender else None,
            "toUser": self.recipient.to_dict() if self.recipient else None,
            "paper": self.paper.to_dict(include_summary=False) if self.paper else None,
            "message": self.message,
            "isRead": self.is_read,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


class PaperSourceClick(db.Model):
    """Track when a user clicks the original paper link."""
    __tablename__ = "paper_source_clicks"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    paper_id = db.Column(db.Integer, db.ForeignKey("papers.id"), nullable=False, index=True)
    context = db.Column(db.String(50), nullable=True)  # dashboard/recommendation/detail/etc.
    clicked_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    user = db.relationship("User", backref="source_clicks")
    paper = db.relationship("Paper", backref="source_clicks")

    def to_dict(self):
        return {
            "id": self.id,
            "userId": self.user_id,
            "paperId": self.paper_id,
            "context": self.context,
            "clickedAt": self.clicked_at.isoformat() if self.clicked_at else None,
        }


class PaperCardClick(db.Model):
    """Track when a user clicks a paper card/title to open details."""
    __tablename__ = "paper_card_clicks"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    paper_id = db.Column(db.Integer, db.ForeignKey("papers.id"), nullable=False, index=True)
    context = db.Column(db.String(50), nullable=True)  # recommendation/dashboard/system-library/etc.
    clicked_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    user = db.relationship("User", backref="card_clicks")
    paper = db.relationship("Paper", backref="card_clicks")

    def to_dict(self):
        return {
            "id": self.id,
            "userId": self.user_id,
            "paperId": self.paper_id,
            "context": self.context,
            "clickedAt": self.clicked_at.isoformat() if self.clicked_at else None,
        }


class PaperPdfDownloadAttempt(db.Model):
    """Per-attempt PDF download audit trail across arXiv/IEEE/Elsevier."""
    __tablename__ = "paper_pdf_download_attempts"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    paper_id = db.Column(db.Integer, db.ForeignKey("papers.id"), nullable=True, index=True)
    article_number = db.Column(db.String(80), nullable=False, index=True)
    source = db.Column(db.String(30), nullable=True, index=True)
    source_url = db.Column(db.String(500), nullable=True)
    success = db.Column(db.Boolean, nullable=False, default=False, index=True)
    reason_code = db.Column(db.String(80), nullable=True, index=True)
    reason_message = db.Column(db.Text, nullable=True)
    downloaded_path = db.Column(db.String(500), nullable=True)
    details_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    paper = db.relationship("Paper", backref="pdf_download_attempts")

    @property
    def details(self):
        if not self.details_json:
            return {}
        try:
            return json.loads(self.details_json)
        except (ValueError, TypeError):
            return {}

    @details.setter
    def details(self, value):
        self.details_json = json.dumps(value or {}, ensure_ascii=False)

    def to_dict(self):
        return {
            "id": self.id,
            "paperId": self.paper_id,
            "articleNumber": self.article_number,
            "source": self.source,
            "sourceUrl": self.source_url,
            "success": bool(self.success),
            "reasonCode": self.reason_code,
            "reasonMessage": self.reason_message,
            "downloadedPath": self.downloaded_path,
            "details": self.details,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


class PaperPdfRetryTask(db.Model):
    """Retry queue for failed PDF downloads."""
    __tablename__ = "paper_pdf_retry_tasks"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    paper_id = db.Column(db.Integer, db.ForeignKey("papers.id"), nullable=True, index=True)
    article_number = db.Column(db.String(80), nullable=False, unique=True, index=True)
    source = db.Column(db.String(30), nullable=True, index=True)
    source_url = db.Column(db.String(500), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)  # pending/running/success/failed
    attempt_count = db.Column(db.Integer, nullable=False, default=0)
    last_reason_code = db.Column(db.String(80), nullable=True)
    last_reason_message = db.Column(db.Text, nullable=True)
    last_downloaded_path = db.Column(db.String(500), nullable=True)
    next_retry_at = db.Column(db.DateTime, nullable=True, index=True)
    last_attempt_at = db.Column(db.DateTime, nullable=True, index=True)
    last_success_at = db.Column(db.DateTime, nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        index=True,
    )

    paper = db.relationship("Paper", backref="pdf_retry_tasks")

    def to_dict(self):
        return {
            "id": self.id,
            "paperId": self.paper_id,
            "articleNumber": self.article_number,
            "source": self.source,
            "sourceUrl": self.source_url,
            "status": self.status,
            "attemptCount": int(self.attempt_count or 0),
            "lastReasonCode": self.last_reason_code,
            "lastReasonMessage": self.last_reason_message,
            "lastDownloadedPath": self.last_downloaded_path,
            "nextRetryAt": self.next_retry_at.isoformat() if self.next_retry_at else None,
            "lastAttemptAt": self.last_attempt_at.isoformat() if self.last_attempt_at else None,
            "lastSuccessAt": self.last_success_at.isoformat() if self.last_success_at else None,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }


class UserDigest(db.Model):
    """Biweekly reading digest, shown in friend module and optionally sent by email."""
    __tablename__ = "user_digests"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    period_start = db.Column(db.DateTime, nullable=False, index=True)
    period_end = db.Column(db.DateTime, nullable=False, index=True)
    subject = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    keywords_json = db.Column(db.Text, nullable=True)
    rec_article_numbers_json = db.Column(db.Text, nullable=True)
    clicked_article_numbers_json = db.Column(db.Text, nullable=True)
    read_count = db.Column(db.Integer, default=0)
    source_click_count = db.Column(db.Integer, default=0)
    is_read = db.Column(db.Boolean, default=False, index=True)
    email_sent_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    user = db.relationship("User", backref="digests")

    @property
    def keywords(self):
        if not self.keywords_json:
            return []
        return json.loads(self.keywords_json)

    @keywords.setter
    def keywords(self, value):
        self.keywords_json = json.dumps(value or [], ensure_ascii=False)

    @property
    def rec_article_numbers(self):
        if not self.rec_article_numbers_json:
            return []
        return json.loads(self.rec_article_numbers_json)

    @rec_article_numbers.setter
    def rec_article_numbers(self, value):
        self.rec_article_numbers_json = json.dumps(value or [], ensure_ascii=False)

    @property
    def clicked_article_numbers(self):
        if not self.clicked_article_numbers_json:
            return []
        return json.loads(self.clicked_article_numbers_json)

    @clicked_article_numbers.setter
    def clicked_article_numbers(self, value):
        self.clicked_article_numbers_json = json.dumps(value or [], ensure_ascii=False)

    def to_dict(self):
        return {
            "id": self.id,
            "subject": self.subject,
            "content": self.content,
            "keywords": self.keywords,
            "recommendedArticleNumbers": self.rec_article_numbers,
            "clickedArticleNumbers": self.clicked_article_numbers,
            "readCount": self.read_count,
            "sourceClickCount": self.source_click_count,
            "isRead": self.is_read,
            "periodStart": self.period_start.isoformat() if self.period_start else None,
            "periodEnd": self.period_end.isoformat() if self.period_end else None,
            "emailSentAt": self.email_sent_at.isoformat() if self.email_sent_at else None,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


class ScholarRating(db.Model):
    """User rates a scholar (identified by name string)."""
    __tablename__ = "scholar_ratings"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    scholar_name = db.Column(db.String(200), nullable=False, index=True)
    score = db.Column(db.Integer, nullable=False)  # 1-5
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (db.UniqueConstraint("user_id", "scholar_name", name="uq_user_scholar_rating"),)

    user = db.relationship("User")

    def to_dict(self):
        return {
            "id": self.id,
            "userId": self.user_id,
            "scholarName": self.scholar_name,
            "score": self.score,
        }


class GroupChat(db.Model):
    """A group chat room."""
    __tablename__ = "group_chats"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False)
    creator_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    creator = db.relationship("User", backref="created_groups")
    members = db.relationship("GroupChatMember", back_populates="group", cascade="all, delete-orphan")
    messages = db.relationship("GroupChatMessage", back_populates="group", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "creatorId": self.creator_id,
            "creatorName": self.creator.username if self.creator else None,
            "memberCount": len(self.members),
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


class GroupChatMember(db.Model):
    """Membership in a group chat."""
    __tablename__ = "group_chat_members"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    group_id = db.Column(db.Integer, db.ForeignKey("group_chats.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False, default="member")  # creator / member
    joined_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (db.UniqueConstraint("group_id", "user_id", name="uq_group_member"),)

    group = db.relationship("GroupChat", back_populates="members")
    user = db.relationship("User", backref="group_memberships")

    def to_dict(self):
        return {
            "id": self.id,
            "groupId": self.group_id,
            "userId": self.user_id,
            "username": self.user.username if self.user else None,
            "role": self.role,
            "joinedAt": self.joined_at.isoformat() if self.joined_at else None,
        }


class GroupChatMessage(db.Model):
    """A message in a group chat."""
    __tablename__ = "group_chat_messages"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    group_id = db.Column(db.Integer, db.ForeignKey("group_chats.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    content = db.Column(db.Text, nullable=True)
    message_type = db.Column(db.String(20), nullable=False, default="text")  # text / paper_share
    paper_id = db.Column(db.Integer, db.ForeignKey("papers.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    group = db.relationship("GroupChat", back_populates="messages")
    sender = db.relationship("User", backref="group_messages")
    paper = db.relationship("Paper", backref="group_shares")

    def to_dict(self):
        d = {
            "id": self.id,
            "groupId": self.group_id,
            "userId": self.user_id,
            "username": self.sender.username if self.sender else None,
            "content": self.content,
            "messageType": self.message_type,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }
        if self.paper:
            d["paper"] = self.paper.to_dict(include_summary=False)
        return d


class UserPreference(db.Model):
    __tablename__ = "user_preferences"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True, index=True)
    journals_json = db.Column(db.Text, nullable=True)
    research_areas_json = db.Column(db.Text, nullable=True)
    recommend_frequency = db.Column(db.String(20), nullable=False, default="daily")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user = db.relationship("User", back_populates="preference")

    @property
    def journals(self):
        if not self.journals_json:
            return []
        return json.loads(self.journals_json)

    @journals.setter
    def journals(self, value):
        self.journals_json = json.dumps(value or [], ensure_ascii=False)

    @property
    def research_areas(self):
        if not self.research_areas_json:
            return []
        return json.loads(self.research_areas_json)

    @research_areas.setter
    def research_areas(self, value):
        self.research_areas_json = json.dumps(value or [], ensure_ascii=False)

    def to_dict(self):
        return {
            "journals": self.journals,
            "researchAreas": self.research_areas,
            "recommendFrequency": self.recommend_frequency,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }


class AboutPageConfig(db.Model):
    """Editable content for the About page."""
    __tablename__ = "about_page_configs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    data_json = db.Column(db.Text, nullable=False)
    updated_by_username = db.Column(db.String(80), nullable=True)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    @property
    def data(self):
        if not self.data_json:
            return {}
        try:
            return json.loads(self.data_json)
        except (ValueError, TypeError):
            return {}

    @data.setter
    def data(self, value):
        self.data_json = json.dumps(value or {}, ensure_ascii=False)

    def to_dict(self):
        return {
            "id": self.id,
            "content": self.data,
            "updatedBy": self.updated_by_username,
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
        }
