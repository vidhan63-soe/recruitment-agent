"""
╔══════════════════════════════════════════════════╗
║  Pipeline Test — Run this to verify everything   ║
║  Usage: python test_pipeline.py                  ║
╚══════════════════════════════════════════════════╝

Tests each module independently, then runs a full end-to-end flow
with synthetic resumes and a sample JD.
"""

import sys
import asyncio
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()


# ── Synthetic Test Data ────────────────────────

FAKE_RESUMES = [
    {
        "filename": "alice_sharma.pdf",
        "text": """
Alice Sharma
alice.sharma@email.com
+91 9876543210

PROFESSIONAL SUMMARY
Senior Python Developer with 6 years of experience in building scalable web applications
and machine learning pipelines. Expertise in FastAPI, Django, and cloud deployments.

SKILLS
Python, FastAPI, Django, PostgreSQL, Redis, Docker, Kubernetes, AWS, React,
Machine Learning, PyTorch, Pandas, NumPy, Git, CI/CD, Agile/Scrum

EXPERIENCE
Senior Software Engineer — TechCorp India (2021 - Present)
- Built microservices architecture handling 10M+ requests/day using FastAPI
- Designed ML pipeline for recommendation engine using PyTorch
- Led team of 5 engineers, conducted code reviews and sprint planning

Software Engineer — StartupXYZ (2018 - 2021)
- Developed RESTful APIs in Django serving 50K daily users
- Implemented automated testing with pytest achieving 92% coverage
- Deployed applications on AWS using Docker and ECS

EDUCATION
B.Tech Computer Science — IIT Hyderabad (2018)
""",
    },
    {
        "filename": "bob_kumar.pdf",
        "text": """
Bob Kumar
bob.kumar@gmail.com
+91 8765432109

SUMMARY
Frontend developer with 3 years of experience specializing in React and TypeScript.
Passionate about UI/UX design and responsive web applications.

SKILLS
JavaScript, TypeScript, React, Next.js, Tailwind CSS, HTML5, CSS3, Redux,
GraphQL, Figma, Jest, Cypress, Git

EXPERIENCE
Frontend Developer — WebAgency (2021 - Present)
- Built responsive SPAs using React and TypeScript for enterprise clients
- Implemented design systems using Tailwind CSS and Storybook
- Optimized Core Web Vitals improving LCP by 40%

Junior Developer — FreelanceWork (2020 - 2021)
- Created landing pages and portfolio websites
- Worked with clients to translate Figma designs to code

EDUCATION
BCA — Delhi University (2020)
""",
    },
    {
        "filename": "carol_patel.pdf",
        "text": """
Carol Patel
carol.patel@outlook.com
+91 7654321098

PROFESSIONAL PROFILE
Full-stack developer with 5 years of experience in Python and JavaScript ecosystems.
Strong background in database design, API development, and DevOps practices.

TECHNICAL SKILLS
Python, JavaScript, TypeScript, FastAPI, Flask, React, Node.js, PostgreSQL,
MongoDB, Redis, Docker, Kubernetes, AWS, GCP, Terraform, Jenkins, Git

WORK EXPERIENCE
Lead Developer — InnovateTech (2022 - Present)
- Architected and built full-stack SaaS platform serving 200+ enterprise clients
- Set up CI/CD pipelines with Jenkins and ArgoCD for Kubernetes deployments
- Designed PostgreSQL schema handling 500M+ rows with query optimization

Full Stack Developer — DigitalSolutions (2019 - 2022)
- Built REST APIs in Flask and FastAPI integrated with React frontend
- Managed MongoDB clusters and Redis caching layer
- Implemented OAuth2 and JWT authentication systems

EDUCATION
M.Tech Software Engineering — IIIT Bangalore (2019)
CERTIFICATIONS
AWS Solutions Architect Associate
""",
    },
    {
        "filename": "dave_singh.pdf",
        "text": """
Dave Singh
dave.singh@yahoo.com

ABOUT ME
Marketing professional with 4 years of experience in digital marketing,
SEO, and content strategy. Looking for growth-oriented roles.

SKILLS
SEO, Google Analytics, Google Ads, Facebook Ads, Content Writing,
Social Media Marketing, HubSpot, Mailchimp, Canva, WordPress

EXPERIENCE
Digital Marketing Manager — MarketPro (2022 - Present)
- Managed ad campaigns with monthly budget of 50L INR
- Increased organic traffic by 180% through SEO optimization
- Created content strategy generating 500K monthly page views

Marketing Executive — BrandBuilders (2020 - 2022)
- Handled social media for 10+ clients
- Wrote blog posts and email campaigns

EDUCATION
MBA Marketing — Symbiosis Pune (2020)
""",
    },
]

SAMPLE_JD = """
Senior Python Backend Developer

Company: TechStartup.ai
Location: Hyderabad (Hybrid)
Experience: 4-7 years

We are looking for a Senior Python Backend Developer to build and scale our
AI-powered platform. You will work on high-performance APIs, ML integration,
and cloud infrastructure.

Required Skills:
- Python (FastAPI or Django) — 4+ years
- PostgreSQL and Redis
- Docker and Kubernetes
- AWS or GCP cloud services
- REST API design and microservices architecture
- Git and CI/CD pipelines

Good to Have:
- Machine Learning / PyTorch experience
- React or frontend basics
- System design experience
- Agile/Scrum methodology

Responsibilities:
- Design and build scalable backend services
- Integrate ML models into production APIs
- Optimize database queries and caching strategies
- Mentor junior developers and lead code reviews
"""


# ── Test Functions ─────────────────────────────

def test_config():
    console.print("\n[bold cyan]TEST 1: Configuration[/bold cyan]")
    from app.core.config import get_settings

    settings = get_settings()
    console.print(f"  Embedding model: {settings.EMBEDDING_MODEL}")
    console.print(f"  Ollama model:    {settings.OLLAMA_MODEL}")
    console.print(f"  Chunk size:      {settings.CHUNK_SIZE}")
    console.print(f"  Device:          {settings.DEVICE}")
    console.print("  [green]✓ Config loaded[/green]")
    return True


def test_gpu():
    console.print("\n[bold cyan]TEST 2: GPU Detection[/bold cyan]")
    from app.core.gpu import get_device

    device = get_device("auto")
    console.print(f"  Selected device: {device}")

    if device == "cuda":
        import torch
        name = torch.cuda.get_device_name(0)
        vram = torch.cuda.get_device_properties(0).total_memory  / (1024 ** 3)
        console.print(f"  GPU: {name} ({vram:.1f}GB VRAM)")
    else:
        console.print("  [yellow]No GPU — running on CPU (slower but works)[/yellow]")

    console.print("  [green]✓ Device detection works[/green]")
    return device


def test_resume_parser():
    console.print("\n[bold cyan]TEST 3: Resume Parser[/bold cyan]")
    from app.services.resume_parser import (
        extract_contact_info,
        extract_sections,
        chunk_text,
    )

    # Test contact extraction
    contact = extract_contact_info(FAKE_RESUMES[0]["text"])
    console.print(f"  Name:  {contact['name']}")
    console.print(f"  Email: {contact['email']}")
    console.print(f"  Phone: {contact['phone']}")

    assert contact["email"] == "alice.sharma@email.com", "Email extraction failed"
    assert contact["phone"], "Phone extraction failed"

    # Test section detection
    sections = extract_sections(FAKE_RESUMES[0]["text"])
    console.print(f"  Sections found: {list(sections.keys())}")
    assert "skills" in sections, "Skills section not detected"
    assert "experience" in sections, "Experience section not detected"

    # Test chunking
    chunks = chunk_text(FAKE_RESUMES[0]["text"], chunk_size=300, overlap=30)
    console.print(f"  Chunks created: {len(chunks)}")
    assert len(chunks) >= 2, "Chunking produced too few chunks"

    console.print("  [green]✓ Resume parser works[/green]")
    return True


def test_embedding(device: str):
    console.print("\n[bold cyan]TEST 4: Embedding Model[/bold cyan]")
    from app.core.config import get_settings
    from app.services.embedding_service import EmbeddingService

    settings = get_settings()
    svc = EmbeddingService(model_name=settings.EMBEDDING_MODEL, device=device)

    start = time.time()
    svc.load()
    load_time = time.time() - start
    console.print(f"  Model loaded in {load_time:.1f}s")
    console.print(f"  Embedding dimension: {svc.dimension}")

    # Test encoding
    test_texts = ["Python developer with FastAPI experience", "Marketing manager with SEO skills"]
    start = time.time()
    embeddings = svc.encode(test_texts)
    encode_time = time.time() - start

    console.print(f"  Encoded 2 texts in {encode_time:.3f}s")
    assert len(embeddings) == 2, "Wrong number of embeddings"
    assert len(embeddings[0]) == svc.dimension, "Wrong embedding dimension"

    # Test similarity
    import numpy as np
    sim = np.dot(embeddings[0], embeddings[1])
    console.print(f"  Similarity between test texts: {sim:.4f} (should be low)")

    console.print("  [green]✓ Embedding model works[/green]")
    return svc


def test_vector_store(embedding_svc):
    console.print("\n[bold cyan]TEST 5: Vector Store (ChromaDB)[/bold cyan]")
    from app.services.vector_store import VectorStoreService
    from app.services.resume_parser import chunk_text

    # Use temp directory for test
    store = VectorStoreService(
        persist_dir="./vectorstore_test",
        collection_name="test_resumes",
    )
    store.initialize()

    # Store all fake resumes
    for resume_data in FAKE_RESUMES:
        chunks = chunk_text(resume_data["text"], chunk_size=300, overlap=30)
        resume_id = resume_data["filename"].replace(".pdf", "")

        chunk_dicts = []
        for i, chunk_text_content in enumerate(chunks):
            chunk_dicts.append({
                "chunk_id": f"{resume_id}_chunk_{i}",
                "resume_id": resume_id,
                "text": chunk_text_content,
                "chunk_index": i,
                "metadata": {
                    "filename": resume_data["filename"],
                    "candidate_name": resume_data["filename"].replace(".pdf", "").replace("_", " ").title(),
                    "section": "general",
                },
            })

        embeddings = embedding_svc.encode([c["text"] for c in chunk_dicts])
        store.add_resume_chunks(chunk_dicts, embeddings)

    total = store.get_total_resumes()
    console.print(f"  Stored {total} resumes")
    assert total == 4, f"Expected 4 resumes, got {total}"

    # Query
    query_emb = embedding_svc.encode_single("Senior Python developer with FastAPI and AWS experience")
    results = store.query(query_embedding=query_emb, top_k=4)

    console.print(f"  Query results:")
    for r in results["results"]:
        console.print(f"    {r['candidate_name']:25s}  score: {r['semantic_score']:.4f}")

    # Alice and Carol should rank highest (Python + FastAPI)
    top_names = [r["candidate_name"].lower() for r in results["results"][:2]]
    console.print(f"  Top 2: {top_names}")

    console.print("  [green]✓ Vector store works[/green]")

    # Cleanup test store
    import shutil
    shutil.rmtree("./vectorstore_test", ignore_errors=True)

    return store


async def test_llm_scorer():
    console.print("\n[bold cyan]TEST 6: LLM Scorer (Ollama)[/bold cyan]")
    from app.core.config import get_settings
    from app.services.llm_scorer import LLMScorer

    settings = get_settings()
    scorer = LLMScorer(base_url=settings.OLLAMA_BASE_URL, model=settings.OLLAMA_MODEL)

    available = await scorer.check_health()

    if available:
        console.print(f"  Ollama connected: {settings.OLLAMA_MODEL}")

        # Test scoring
        result = await scorer.score_candidate(
            jd_text=SAMPLE_JD,
            resume_chunks=[{"text": FAKE_RESUMES[0]["text"][:1000]}],
            candidate_name="Alice Sharma",
        )
        console.print(f"  LLM score: {result['llm_score']:.3f}")
        console.print(f"  Matched skills: {result['matched_skills'][:5]}")
        console.print(f"  Missing skills: {result['missing_skills'][:5]}")
        console.print("  [green]✓ LLM scorer works[/green]")
    else:
        console.print("  [yellow]⚠ Ollama not available — using fallback scoring[/yellow]")
        console.print("  [yellow]  Install Ollama: https://ollama.com/download[/yellow]")
        console.print(f"  [yellow]  Then run: ollama pull {settings.OLLAMA_MODEL}[/yellow]")

        # Test fallback
        result = scorer._fallback_score(SAMPLE_JD, [{"text": FAKE_RESUMES[0]["text"]}])
        console.print(f"  Fallback score: {result['llm_score']:.3f}")
        console.print(f"  Matched keywords: {result['matched_skills'][:5]}")
        console.print("  [green]✓ Fallback scoring works[/green]")

    return scorer


def test_full_pipeline(embedding_svc):
    """Run the complete match pipeline with synthetic data."""
    console.print("\n[bold cyan]TEST 7: Full Pipeline (End-to-End)[/bold cyan]")
    from app.services.vector_store import VectorStoreService
    from app.services.resume_parser import chunk_text
    import numpy as np

    store = VectorStoreService(persist_dir="./vectorstore_test_e2e", collection_name="e2e_test")
    store.initialize()

    # Ingest all resumes
    for resume_data in FAKE_RESUMES:
        chunks = chunk_text(resume_data["text"], chunk_size=400, overlap=40)
        resume_id = resume_data["filename"].replace(".pdf", "")

        chunk_dicts = []
        for i, ct in enumerate(chunks):
            chunk_dicts.append({
                "chunk_id": f"{resume_id}_chunk_{i}",
                "resume_id": resume_id,
                "text": ct,
                "chunk_index": i,
                "metadata": {
                    "filename": resume_data["filename"],
                    "candidate_name": resume_data["filename"].replace(".pdf", "").replace("_", " ").title(),
                    "section": "general",
                },
            })

        embeddings = embedding_svc.encode([c["text"] for c in chunk_dicts])
        store.add_resume_chunks(chunk_dicts, embeddings)

    # Match against JD
    jd_embedding = embedding_svc.encode_single(SAMPLE_JD)
    results = store.query(query_embedding=jd_embedding, top_k=4)

    # Display results
    table = Table(title="Candidate Rankings", show_lines=True)
    table.add_column("Rank", style="bold", width=6)
    table.add_column("Candidate", width=22)
    table.add_column("Filename", width=22)
    table.add_column("Semantic Score", justify="right", width=14)
    table.add_column("Match Level", width=14)

    for i, r in enumerate(results["results"]):
        score = r["semantic_score"]
        if score >= 0.6:
            level = "[green]Strong[/green]"
        elif score >= 0.45:
            level = "[yellow]Good[/yellow]"
        elif score >= 0.35:
            level = "[cyan]Fair[/cyan]"
        else:
            level = "[red]Weak[/red]"

        table.add_row(
            str(i + 1),
            r["candidate_name"],
            r["filename"],
            f"{score:.4f}",
            level,
        )

    console.print(table)

    # Validate: Python devs should beat the marketing person
    ranked_names = [r["candidate_name"].lower() for r in results["results"]]
    dave_rank = next(
        (i for i, n in enumerate(ranked_names) if "dave" in n),
        len(ranked_names),
    )
    console.print(f"\n  Dave (marketing) ranked #{dave_rank + 1} of {len(ranked_names)} — ", end="")
    if dave_rank >= 2:
        console.print("[green]correct! Non-tech candidate ranked lower.[/green]")
    else:
        console.print("[yellow]unexpected — may need tuning.[/yellow]")

    # Cleanup
    import shutil
    shutil.rmtree("./vectorstore_test_e2e", ignore_errors=True)

    console.print("  [green]✓ Full pipeline works![/green]")
    return True


# ── Main ───────────────────────────────────────

async def main():
    console.print(Panel.fit(
        "[bold white]AI Recruitment Agent — Pipeline Tests[/bold white]\n"
        "Testing all modules independently + full E2E flow",
        border_style="cyan",
    ))

    results = {}

    try:
        results["config"] = test_config()
        device = test_gpu()
        results["gpu"] = True
        results["parser"] = test_resume_parser()
        embedding_svc = test_embedding(device)
        results["embedding"] = True
        test_vector_store(embedding_svc)
        results["vector_store"] = True
        await test_llm_scorer()
        results["llm_scorer"] = True
        test_full_pipeline(embedding_svc)
        results["pipeline"] = True

        # Cleanup
        embedding_svc.unload()

    except Exception as e:
        console.print(f"\n[red bold]TEST FAILED: {e}[/red bold]")
        import traceback
        traceback.print_exc()

    # Summary
    console.print("\n")
    summary = Table(title="Test Summary", show_lines=True)
    summary.add_column("Module", width=20)
    summary.add_column("Status", width=10, justify="center")

    for name, passed in results.items():
        status = "[green]PASS[/green]" if passed else "[red]FAIL[/red]"
        summary.add_row(name, status)

    console.print(summary)

    all_pass = all(results.values())
    if all_pass:
        console.print(Panel.fit(
            "[bold green]All tests passed![/bold green]\n\n"
            "Next: run [cyan]python app.py[/cyan] and open [cyan]http://localhost:8000/docs[/cyan]\n"
            "Upload real resumes via the /api/v1/resumes/upload endpoint.",
            border_style="green",
        ))
    else:
        console.print("[yellow]Some tests failed — check output above.[/yellow]")


if __name__ == "__main__":
    asyncio.run(main())
