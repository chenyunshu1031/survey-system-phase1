from pymongo import ASCENDING, DESCENDING
from pymongo.database import Database


def field(bson_type, **extra):
    return {"bsonType": bson_type, **extra}


SCHEMAS = {
    "users": {
        "required": ["username", "usernameKey", "passwordHash", "createdAt", "schemaVersion"],
        "properties": {
            "username": field("string"),
            "usernameKey": field("string"),
            "passwordHash": field("string"),
            "createdAt": field("date"),
            "schemaVersion": field("int"),
        },
    },
    "surveys": {
        "required": ["ownerId", "slug", "title", "description", "allowAnonymous", "allowMultipleSubmissions", "status", "createdAt", "updatedAt", "schemaVersion"],
        "properties": {
            "ownerId": field("objectId"),
            "slug": field("string"),
            "title": field("string"),
            "description": field("string"),
            "allowAnonymous": field("bool"),
            "allowMultipleSubmissions": field("bool"),
            "status": field("string", enum=["draft", "published", "closed"]),
            "activeQuestionMutations": field("int", minimum=0),
            "activeSubmissions": field("int", minimum=0),
            "configurationRevision": field("int", minimum=0),
            "submissionRevision": field("int", minimum=0),
            "deadlineAt": field(["date", "null"]),
            "createdAt": field("date"),
            "updatedAt": field("date"),
            "publishedAt": field(["date", "null"]),
            "closedAt": field(["date", "null"]),
            "schemaVersion": field("int"),
        },
    },
    "questions": {
        "required": ["surveyId", "order", "type", "title", "required", "options", "validation", "jumpRules", "schemaVersion"],
        "properties": {
            "surveyId": field("objectId"),
            "order": field("int", minimum=1),
            "type": field("string", enum=["single", "multiple", "text", "number"]),
            "title": field("string"),
            "required": field("bool"),
            "options": field("array", items={"bsonType": "object", "required": ["id", "label"], "properties": {"id": field("string"), "label": field("string")}}),
            "validation": field("object", properties={
                "minSelections": field(["int", "long", "null"], minimum=0),
                "maxSelections": field(["int", "long", "null"], minimum=1),
                "minLength": field(["int", "long", "null"], minimum=0),
                "maxLength": field(["int", "long", "null"], minimum=1),
                "minValue": field(["double", "int", "long", "null"]),
                "maxValue": field(["double", "int", "long", "null"]),
                "integerOnly": field(["bool", "null"]),
            }),
            "jumpRules": field("array", maxItems=30, items={
                "bsonType": "object", "required": ["id", "priority", "operator", "targetQuestionId"],
                "properties": {
                    "id": field("string", minLength=1),
                    "priority": field(["int", "long"], minimum=1),
                    "operator": field("string", enum=["equals", "containsAny", "containsAll", "eq", "gt", "gte", "lt", "lte", "between"]),
                    "targetQuestionId": field("string", minLength=1),
                    "optionIds": field("array", items=field("string", minLength=1), uniqueItems=True),
                    "value": field(["double", "int", "long"]),
                    "minValue": field(["double", "int", "long"]),
                    "maxValue": field(["double", "int", "long"]),
                },
            }),
            "schemaVersion": field("int"),
        },
    },
    "responses": {
        "required": ["surveyId", "respondentId", "isAnonymous", "answers", "visitedQuestionIds", "submittedAt", "singleSubmission", "schemaVersion"],
        "properties": {
            "surveyId": field("objectId"),
            "respondentId": field("objectId"),
            "isAnonymous": field("bool"),
            "answers": field("array", items={
                "bsonType": "object",
                "required": ["questionId", "value"],
                "properties": {
                    "questionId": field("string", minLength=1),
                    "value": {"anyOf": [
                        field("string", minLength=1), field(["double", "int", "long"]),
                        field("array", items=field("string", minLength=1), minItems=1, uniqueItems=True),
                    ]},
                },
            }),
            "visitedQuestionIds": field("array", items=field("string", minLength=1), minItems=1, uniqueItems=True),
            "submittedAt": field("date"),
            "singleSubmission": field("bool"),
            "schemaVersion": field("int"),
        },
    },
}


def initialize_database(db: Database) -> None:
    """Create or refresh validators and indexes. Safe to call more than once."""
    db.command("ping")
    existing = set(db.list_collection_names())
    for name, schema in SCHEMAS.items():
        validator = {"$jsonSchema": {"bsonType": "object", **schema}}
        if name in existing:
            db.command({"collMod": name, "validator": validator, "validationLevel": "strict"})
        else:
            db.create_collection(name, validator=validator, validationLevel="strict")

    db.users.create_index("usernameKey", unique=True, name="uniq_username_key")
    db.surveys.create_index("slug", unique=True, name="uniq_survey_slug")
    db.surveys.create_index([("ownerId", ASCENDING), ("createdAt", DESCENDING)], name="owner_recent")
    db.questions.create_index([("surveyId", ASCENDING), ("order", ASCENDING)], unique=True, name="uniq_survey_order")
    db.responses.create_index(
        [("surveyId", ASCENDING), ("submittedAt", DESCENDING), ("_id", DESCENDING)],
        name="survey_response_entries",
    )
    old_index = db.responses.index_information().get("survey_recent_responses")
    if old_index and old_index["key"] == [("surveyId", ASCENDING), ("submittedAt", DESCENDING)] and not old_index.get("unique"):
        db.responses.drop_index("survey_recent_responses")
    db.responses.create_index(
        [("surveyId", ASCENDING), ("respondentId", ASCENDING)],
        unique=True,
        partialFilterExpression={"singleSubmission": True},
        name="uniq_single_submission",
    )

    # The first-stage application runs as one server process. Recover counters if
    # that process was interrupted between reserving and releasing an operation.
    db.surveys.update_many({}, {"$set": {"activeQuestionMutations": 0, "activeSubmissions": 0}})
