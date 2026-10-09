from sqlalchemy.orm import Session

from pecha_api.feedback.feedback_models import Feedback


def create_feedback(db: Session, feedback: Feedback) -> Feedback:
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return feedback
