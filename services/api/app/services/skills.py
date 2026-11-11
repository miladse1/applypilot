"""Skill normalization, aliases, and related-skill rules.

Absence from a profile is never treated as proof that a person lacks a skill.
"""

from __future__ import annotations

import re

_ENTRIES: list[tuple[str, str, str, list[str]]] = [
    # Programming languages
    ("python", "Python", "programming_language", ["py", "python3", "python 3"]),
    ("java", "Java", "programming_language", ["java se", "java 8", "java 11", "java 17", "core java"]),
    ("javascript", "JavaScript", "programming_language", ["js", "ecmascript", "es6", "vanilla js"]),
    ("typescript", "TypeScript", "programming_language", ["ts"]),
    ("sql", "SQL", "programming_language", ["structured query language", "t-sql", "tsql", "pl/sql", "plsql", "ansi sql"]),
    ("c", "C", "programming_language", ["c language", "c programming"]),
    ("cpp", "C++", "programming_language", ["c++", "cpp", "c plus plus"]),
    ("csharp", "C#", "programming_language", ["c#", "c sharp", "csharp"]),
    ("go", "Go", "programming_language", ["golang", "go lang"]),
    ("rust", "Rust", "programming_language", []),
    ("ruby", "Ruby", "programming_language", []),
    ("php", "PHP", "programming_language", []),
    ("kotlin", "Kotlin", "programming_language", []),
    ("swift", "Swift", "programming_language", []),
    ("scala", "Scala", "programming_language", []),
    ("r", "R", "programming_language", ["r language", "r programming", "rstudio"]),
    ("matlab", "MATLAB", "programming_language", []),
    ("bash", "Bash", "programming_language", ["shell scripting", "shell script", "bash scripting", "shell", "unix shell"]),
    ("powershell", "PowerShell", "programming_language", []),
    ("perl", "Perl", "programming_language", []),
    ("dart", "Dart", "programming_language", []),
    ("cobol", "COBOL", "programming_language", []),
    ("vba", "VBA", "programming_language", ["visual basic for applications"]),
    ("html", "HTML", "programming_language", ["html5"]),
    ("css", "CSS", "programming_language", ["css3"]),
    ("solidity", "Solidity", "programming_language", []),
    ("assembly", "Assembly", "programming_language", ["assembly language", "x86 assembly"]),
    ("verilog", "Verilog", "programming_language", ["systemverilog"]),
    # Web and application frameworks
    ("react", "React", "framework", ["react.js", "reactjs", "react js"]),
    ("nextjs", "Next.js", "framework", ["next.js", "nextjs", "next js"]),
    ("angular", "Angular", "framework", ["angularjs", "angular.js"]),
    ("vue", "Vue.js", "framework", ["vue", "vuejs", "vue.js", "nuxt"]),
    ("svelte", "Svelte", "framework", []),
    ("node", "Node.js", "framework", ["nodejs", "node.js", "node js"]),
    ("express", "Express", "framework", ["express.js", "expressjs"]),
    ("nestjs", "NestJS", "framework", ["nest.js"]),
    ("django", "Django", "framework", []),
    ("flask", "Flask", "framework", []),
    ("fastapi", "FastAPI", "framework", ["fast api"]),
    ("spring", "Spring", "framework", ["spring framework"]),
    ("spring-boot", "Spring Boot", "framework", ["springboot"]),
    ("dotnet", ".NET", "framework", [".net", "dotnet", ".net core", "asp.net", "asp.net core"]),
    ("rails", "Ruby on Rails", "framework", ["rails", "ruby on rails", "ror"]),
    ("laravel", "Laravel", "framework", []),
    ("graphql", "GraphQL", "framework", []),
    ("redux", "Redux", "framework", []),
    ("tailwind", "Tailwind CSS", "framework", ["tailwind", "tailwindcss"]),
    ("bootstrap", "Bootstrap", "framework", []),
    ("jquery", "jQuery", "framework", []),
    ("react-native", "React Native", "framework", []),
    ("flutter", "Flutter", "framework", []),
    ("android", "Android", "framework", ["android sdk", "android development"]),
    ("ios", "iOS", "framework", ["ios development", "swiftui", "uikit"]),
    ("electron", "Electron", "framework", []),
    ("hibernate", "Hibernate", "framework", ["jpa"]),
    ("junit", "JUnit", "tool", []),
    ("pytest", "pytest", "tool", []),
    ("jest", "Jest", "tool", []),
    ("selenium", "Selenium", "tool", []),
    ("cypress", "Cypress", "tool", []),
    ("playwright", "Playwright", "tool", []),
    ("postman", "Postman", "tool", []),
    # Data, analytics, and big data
    ("pandas", "pandas", "data", []),
    ("numpy", "NumPy", "data", []),
    ("scipy", "SciPy", "data", []),
    ("matplotlib", "Matplotlib", "data", []),
    ("seaborn", "Seaborn", "data", []),
    ("plotly", "Plotly", "data", []),
    ("jupyter", "Jupyter", "tool", ["jupyter notebook", "jupyter notebooks", "jupyterlab"]),
    ("spark", "Apache Spark", "data", ["spark", "apache spark", "pyspark", "spark sql"]),
    ("hadoop", "Hadoop", "data", ["hdfs", "apache hadoop", "mapreduce"]),
    ("hive", "Hive", "data", ["apache hive"]),
    ("kafka", "Kafka", "data", ["apache kafka"]),
    ("airflow", "Airflow", "data", ["apache airflow"]),
    ("dbt", "dbt", "data", ["data build tool"]),
    ("etl", "ETL", "data", ["etl/elt", "elt", "extract transform load", "etl pipelines", "data pipelines", "data pipeline"]),
    ("data-modeling", "Data Modeling", "data", ["data modelling", "dimensional modeling", "star schema"]),
    ("data-warehousing", "Data Warehousing", "data", ["data warehouse", "data warehouses", "data warehousing"]),
    ("snowflake", "Snowflake", "data", []),
    ("databricks", "Databricks", "data", []),
    ("bigquery", "BigQuery", "data", ["google bigquery"]),
    ("redshift", "Redshift", "data", ["amazon redshift"]),
    ("tableau", "Tableau", "data", []),
    ("power-bi", "Power BI", "data", ["powerbi", "power bi", "microsoft power bi"]),
    ("looker", "Looker", "data", []),
    ("excel", "Excel", "tool", ["microsoft excel", "ms excel", "advanced excel"]),
    ("statistics", "Statistics", "concept", ["statistical analysis", "probability and statistics", "probability & statistics"]),
    ("ab-testing", "A/B Testing", "concept", ["a/b testing", "ab testing", "experimentation"]),
    ("flink", "Apache Flink", "data", ["flink"]),
    ("beam", "Apache Beam", "data", []),
    ("informatica", "Informatica", "data", []),
    ("ssis", "SSIS", "data", []),
    ("sas", "SAS", "data", []),
    ("spss", "SPSS", "data", []),
    # Machine learning and AI
    ("machine-learning", "Machine Learning", "ml", ["ml", "machine-learning"]),
    ("deep-learning", "Deep Learning", "ml", []),
    ("scikit-learn", "scikit-learn", "ml", ["sklearn", "scikit learn"]),
    ("xgboost", "XGBoost", "ml", []),
    ("lightgbm", "LightGBM", "ml", []),
    ("tensorflow", "TensorFlow", "ml", []),
    ("keras", "Keras", "ml", []),
    ("pytorch", "PyTorch", "ml", ["torch"]),
    ("hugging-face", "Hugging Face", "ml", ["huggingface", "transformers library", "hugging face transformers"]),
    ("nlp", "NLP", "ml", ["natural language processing"]),
    ("computer-vision", "Computer Vision", "ml", ["opencv"]),
    ("llm", "LLMs", "ml", ["llm", "llms", "large language models", "large language model", "claude api", "anthropic api", "openai api"]),
    ("generative-ai", "Generative AI", "ml", ["genai", "gen ai", "generative ai"]),
    ("langchain", "LangChain", "ml", []),
    ("rag", "RAG", "ml", ["retrieval augmented generation", "retrieval-augmented generation"]),
    ("prompt-engineering", "Prompt Engineering", "ml", []),
    ("mlops", "MLOps", "ml", ["ml ops"]),
    ("mlflow", "MLflow", "ml", []),
    ("reinforcement-learning", "Reinforcement Learning", "ml", []),
    ("time-series", "Time Series Analysis", "ml", ["time series", "forecasting"]),
    ("feature-engineering", "Feature Engineering", "ml", []),
    # Databases
    ("postgresql", "PostgreSQL", "database", ["postgres", "psql", "postgre sql"]),
    ("mysql", "MySQL", "database", []),
    ("sql-server", "SQL Server", "database", ["microsoft sql server", "mssql", "ms sql"]),
    ("oracle", "Oracle Database", "database", ["oracle", "oracle db", "oracle database"]),
    ("sqlite", "SQLite", "database", []),
    ("mongodb", "MongoDB", "database", ["mongo"]),
    ("redis", "Redis", "database", []),
    ("cassandra", "Cassandra", "database", ["apache cassandra"]),
    ("dynamodb", "DynamoDB", "database", ["amazon dynamodb"]),
    ("elasticsearch", "Elasticsearch", "database", ["elastic search", "opensearch"]),
    ("firebase", "Firebase", "database", ["firestore"]),
    ("nosql", "NoSQL", "database", ["no sql"]),
    ("neo4j", "Neo4j", "database", []),
    ("supabase", "Supabase", "database", []),
    # Cloud
    ("aws", "AWS", "cloud", ["amazon web services", "amazon aws"]),
    ("gcp", "Google Cloud", "cloud", ["google cloud platform", "google cloud", "gcp"]),
    ("azure", "Azure", "cloud", ["microsoft azure"]),
    ("ec2", "EC2", "cloud", ["amazon ec2"]),
    ("s3", "S3", "cloud", ["amazon s3"]),
    ("lambda", "AWS Lambda", "cloud", ["aws lambda", "lambda functions"]),
    ("serverless", "Serverless", "cloud", []),
    ("cloudformation", "CloudFormation", "cloud", []),
    ("heroku", "Heroku", "cloud", []),
    ("vercel", "Vercel", "cloud", []),
    # DevOps and infrastructure
    ("docker", "Docker", "devops", ["dockerfile", "docker compose", "docker-compose", "containers", "containerization"]),
    ("kubernetes", "Kubernetes", "devops", ["k8s", "eks", "aks", "gke"]),
    ("terraform", "Terraform", "devops", []),
    ("ansible", "Ansible", "devops", []),
    ("jenkins", "Jenkins", "devops", []),
    ("github-actions", "GitHub Actions", "devops", ["github actions"]),
    ("gitlab-ci", "GitLab CI", "devops", ["gitlab ci/cd", "gitlab ci"]),
    ("cicd", "CI/CD", "devops", ["ci cd", "ci/cd", "continuous integration", "continuous delivery", "continuous deployment", "ci/cd pipelines"]),
    ("linux", "Linux", "devops", ["unix", "ubuntu", "red hat", "rhel"]),
    ("git", "Git", "tool", ["git version control", "version control", "github", "gitlab", "bitbucket"]),
    ("helm", "Helm", "devops", []),
    ("prometheus", "Prometheus", "devops", []),
    ("grafana", "Grafana", "devops", []),
    ("datadog", "Datadog", "devops", []),
    ("splunk", "Splunk", "devops", []),
    ("nginx", "NGINX", "devops", ["nginx"]),
    ("microservices", "Microservices", "concept", ["microservice", "microservices architecture"]),
    ("distributed-systems", "Distributed Systems", "concept", []),
    ("networking", "Networking", "concept", ["tcp/ip", "computer networking", "computer networks"]),
    ("observability", "Observability", "concept", ["monitoring and alerting"]),
    # Engineering practices and concepts
    ("rest-apis", "REST APIs", "concept", ["rest", "rest api", "restful", "restful apis", "rest apis", "restful api", "web apis", "apis"]),
    ("grpc", "gRPC", "concept", []),
    ("oop", "Object-Oriented Programming", "concept", ["object oriented programming", "object-oriented programming", "oop", "object-oriented design", "object oriented design"]),
    ("data-structures", "Data Structures & Algorithms", "concept", ["data structures", "algorithms", "data structures and algorithms", "data structures & algorithms", "dsa"]),
    ("unit-testing", "Unit Testing", "concept", ["unit tests", "automated testing", "test automation", "testing"]),
    ("tdd", "Test-Driven Development", "concept", ["tdd", "test driven development"]),
    ("agile", "Agile", "concept", ["scrum", "agile methodologies", "kanban"]),
    ("system-design", "System Design", "concept", ["systems design", "software architecture"]),
    ("design-patterns", "Design Patterns", "concept", []),
    ("security", "Application Security", "concept", ["owasp", "secure coding", "application security"]),
    ("authentication", "Authentication (OAuth/JWT)", "concept", ["oauth", "oauth2", "jwt", "sso"]),
    ("websockets", "WebSockets", "concept", ["websocket"]),
    ("concurrency", "Concurrency", "concept", ["multithreading", "multi-threading", "parallel programming"]),
    ("sdlc", "SDLC", "concept", ["software development life cycle", "software development lifecycle"]),
    ("jira", "Jira", "tool", []),
    ("confluence", "Confluence", "tool", []),
    ("figma", "Figma", "tool", []),
    ("servicenow", "ServiceNow", "tool", []),
    ("salesforce", "Salesforce", "tool", []),
    ("sap", "SAP", "tool", []),
    ("mainframe", "Mainframe", "tool", ["z/os", "jcl"]),
    ("blockchain", "Blockchain", "concept", []),
    ("embedded", "Embedded Systems", "concept", ["embedded systems", "firmware", "rtos"]),
    ("cuda", "CUDA", "tool", []),
    ("unity", "Unity", "tool", []),
    # Engineering software and other domains kept from the original catalog
    ("autocad", "AutoCAD", "engineering_software", ["auto cad"]),
    ("civil-3d", "Civil 3D", "engineering_software", ["autocad civil 3d"]),
    ("gis", "GIS", "engineering_software", ["geographic information systems", "arcgis", "qgis"]),
    ("solidworks", "SolidWorks", "engineering_software", []),
    ("transportation-engineering", "Transportation Engineering", "industry", ["traffic engineering", "highway engineering"]),
    ("structural-engineering", "Structural Engineering", "industry", []),
    # Soft skills (only matched when a posting names them explicitly)
    ("communication", "Communication", "soft_skill", ["written communication", "verbal communication", "communication skills"]),
    ("teamwork", "Teamwork", "soft_skill", ["collaboration", "team player"]),
    ("problem-solving", "Problem Solving", "soft_skill", ["problem-solving", "problem solving skills"]),
    ("leadership", "Leadership", "soft_skill", []),
    ("french", "French", "language", ["bilingual french", "french language", "bilingual (english/french)", "bilingual english and french"]),
]

CATALOG: dict[str, dict] = {key: {"name": name, "category": category, "aliases": aliases} for key, name, category, aliases in _ENTRIES}

# Aliases that are ordinary words. They count only inside a skills list, never in free text.
AMBIGUOUS_IN_TEXT = {"assembly", "excel", "r", "c", "go", "rest", "shell", "testing", "apis", "containers", "spark", "unity", "dart", "swift", "sap", "oracle", "lambda", "torch", "rails", "express", "spring", "agile", "kanban", "scrum", "version control", "ml", "communication", "collaboration", "leadership", "teamwork", "problem solving", "forecasting", "algorithms", "data structures", "security", "sso", "experimentation", "embedded", "firmware", "elt", "github", "gitlab", "unix", "ubuntu", "red hat", "data pipeline", "data pipelines", "networking", "jpa", "french"}

# A specific skill can satisfy a broader requirement. The reverse is only partial.
IMPLIES: dict[str, set[str]] = {
    "postgresql": {"sql"},
    "mysql": {"sql"},
    "sql-server": {"sql"},
    "oracle": {"sql"},
    "sqlite": {"sql"},
    "snowflake": {"sql", "data-warehousing"},
    "bigquery": {"sql", "data-warehousing"},
    "redshift": {"sql", "data-warehousing"},
    "dbt": {"sql", "etl"},
    "airflow": {"etl"},
    "spark": {"etl"},
    "django": {"python"},
    "fastapi": {"python", "rest-apis"},
    "flask": {"python", "rest-apis"},
    "pandas": {"python"},
    "numpy": {"python"},
    "scikit-learn": {"python", "machine-learning"},
    "xgboost": {"machine-learning"},
    "tensorflow": {"machine-learning", "deep-learning"},
    "pytorch": {"machine-learning", "deep-learning"},
    "keras": {"deep-learning"},
    "typescript": {"javascript"},
    "react": {"javascript"},
    "nextjs": {"react", "javascript"},
    "angular": {"javascript"},
    "vue": {"javascript"},
    "node": {"javascript"},
    "express": {"node", "rest-apis"},
    "spring-boot": {"java", "spring", "rest-apis"},
    "spring": {"java"},
    "kotlin": {"java"},
    "github-actions": {"cicd"},
    "gitlab-ci": {"cicd"},
    "jenkins": {"cicd"},
    "kubernetes": {"docker"},
    "ec2": {"aws"},
    "s3": {"aws"},
    "lambda": {"aws"},
    "dynamodb": {"aws", "nosql"},
    "mongodb": {"nosql"},
    "firebase": {"nosql"},
    "cassandra": {"nosql"},
    "civil-3d": {"autocad"},
    "junit": {"unit-testing"},
    "pytest": {"unit-testing"},
    "jest": {"unit-testing"},
}

RELATED: dict[str, set[str]] = {
    "kubernetes": {"docker"},
    "aws": {"gcp", "azure"},
    "gcp": {"aws", "azure"},
    "azure": {"aws", "gcp"},
    "postgresql": {"mysql", "sql-server", "oracle"},
    "mysql": {"postgresql", "sql-server"},
    "sql-server": {"postgresql", "mysql"},
    "react": {"angular", "vue"},
    "angular": {"react", "vue"},
    "vue": {"react", "angular"},
    "tensorflow": {"pytorch"},
    "pytorch": {"tensorflow"},
    "tableau": {"power-bi", "looker"},
    "power-bi": {"tableau", "looker"},
    "snowflake": {"bigquery", "redshift", "databricks"},
    "databricks": {"spark", "snowflake"},
    "github-actions": {"jenkins", "gitlab-ci"},
    "jenkins": {"github-actions", "gitlab-ci"},
    "terraform": {"cloudformation"},
    "kafka": {"spark"},
    "java": {"kotlin", "scala", "csharp"},
    "csharp": {"java"},
    "flask": {"fastapi", "django"},
    "fastapi": {"flask", "django"},
    "django": {"flask", "fastapi"},
    "civil-3d": {"gis"},
}

_ALIAS_TO_KEY: dict[str, str] = {}
for key, meta in CATALOG.items():
    _ALIAS_TO_KEY[key] = key
    _ALIAS_TO_KEY[meta["name"].lower()] = key
    for alias in meta["aliases"]:
        _ALIAS_TO_KEY[alias.lower()] = key


def _clean(value: str) -> str:
    text = value.lower().strip()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9+#.\s/-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_skill(value: str) -> tuple[str, str, str]:
    """Return canonical key, display name, and category."""
    cleaned = _clean(value)
    if cleaned in _ALIAS_TO_KEY:
        key = _ALIAS_TO_KEY[cleaned]
        meta = CATALOG[key]
        return key, meta["name"], meta["category"]
    slug = re.sub(r"[^a-z0-9]+", "-", cleaned).strip("-") or "unknown"
    display = value.strip()
    if slug in CATALOG:
        meta = CATALOG[slug]
        return slug, meta["name"], meta["category"]
    return slug, display[:120], "other"


_PHRASES = sorted(_ALIAS_TO_KEY.keys(), key=len, reverse=True)
_PHRASE_RE = {
    phrase: re.compile(r"(?<![a-z0-9+#])" + re.escape(phrase) + r"(?![a-z0-9+#]|\.[a-z])")
    for phrase in _PHRASES
}
_CASE_SENSITIVE = {"go": re.compile(r"\bGo\b(?!\s+(?:to|and|with|beyond|live|through|above))"), "r": re.compile(r"(?<![\w-])R(?![\w-])"), "c": re.compile(r"(?<![\w-])C(?![\w+#-])"), "rest": re.compile(r"\bREST\b"), "spark": re.compile(r"\bSpark\b"), "swift": re.compile(r"\bSwift\b"), "unity": re.compile(r"\bUnity\b"), "dart": re.compile(r"\bDart\b"), "sap": re.compile(r"\bSAP\b"), "oracle": re.compile(r"\bOracle\b"), "rails": re.compile(r"\bRails\b"), "express": re.compile(r"\bExpress(\.js)?\b"), "spring": re.compile(r"\bSpring\b"), "ml": re.compile(r"\bML\b"), "lambda": re.compile(r"\bLambda\b"), "torch": re.compile(r"\btorch\b"), "excel": re.compile(r"\bExcel\b(?!\s+(?:at|in)\b)"), "assembly": re.compile(r"\bAssembly (?:language|code|programming)\b|\bx86\b|\bARM assembly\b")}


def find_skills_in_text(text: str, *, list_context: bool = False) -> list[tuple[str, str, str]]:
    """Find catalog skills mentioned in text. Longer aliases win.

    In free text, aliases that are ordinary words ("go", "rest", "testing") need
    their technical casing or are skipped. In a comma-separated skills list
    (`list_context=True`) every alias counts.
    """
    cleaned = _clean(text)
    haystack = f" {cleaned} "
    found: dict[str, tuple[str, str, str]] = {}
    consumed: list[tuple[int, int]] = []
    for phrase in _PHRASES:
        key = _ALIAS_TO_KEY[phrase]
        if not list_context and phrase in AMBIGUOUS_IN_TEXT:
            pattern = _CASE_SENSITIVE.get(phrase)
            if pattern is None or not pattern.search(text):
                continue
            if key not in found:
                meta = CATALOG[key]
                found[key] = (key, meta["name"], meta["category"])
            continue
        for match in _PHRASE_RE[phrase].finditer(haystack):
            span = match.span()
            if any(start <= span[0] and span[1] <= end for start, end in consumed):
                continue
            consumed.append(span)
            if key not in found:
                meta = CATALOG[key]
                found[key] = (key, meta["name"], meta["category"])
    return list(found.values())


def relationship(requirement_key: str, possessed_key: str) -> str:
    if requirement_key == possessed_key:
        return "exact"
    if requirement_key in IMPLIES.get(possessed_key, set()):
        return "implies"
    if possessed_key in RELATED.get(requirement_key, set()) or requirement_key in RELATED.get(possessed_key, set()):
        return "related"
    return "none"
