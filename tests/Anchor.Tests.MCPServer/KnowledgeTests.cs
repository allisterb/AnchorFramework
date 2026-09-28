namespace Anchor.Tests.MCPServer;

using System;
using System.Linq;

using Anchor.MCPServer;

/// <summary>
/// The knowledge base: that it loads, that a name cannot escape it, and that it still describes the
/// tools it is about.
/// </summary>
/// <remarks>
/// Reference material that has fallen behind the code is worse than none, because it is believed.
/// <see cref="EveryVerdictTheCheckerCanEmitIsDocumented"/> is the test that makes adding a verdict
/// fail until the article explaining it is updated.
/// </remarks>
public class KnowledgeTests : TestsRuntime
{
    #region Methods

    /// <summary>Articles load from the assembly, with their front matter read and removed.</summary>
    [Fact]
    public void ArticlesLoadWithTitlesAndDescriptions()
    {
        var articles = KnowledgeBase.Articles;
        Assert.NotEmpty(articles);

        foreach (var a in articles)
        {
            Assert.False(string.IsNullOrWhiteSpace(a.Title), $"{a.Name} has no title");
            Assert.False(string.IsNullOrWhiteSpace(a.Description), $"{a.Name} has no description");
            Assert.False(string.IsNullOrWhiteSpace(a.Content), $"{a.Name} has no body");

            // The front matter is metadata, not content: it must not reach the reader.
            Assert.DoesNotContain("description:", a.Content, StringComparison.Ordinal);
            Assert.StartsWith("#", a.Content.TrimStart());

            // The title is the article's own, not the fallback to its file name.
            Assert.NotEqual(a.Name, a.Title);
        }

        // The ones the tool descriptions send an agent to by name must exist.
        foreach (var required in new[]
                 { "reading-verdicts", "the-modelled-subset", "writing-a-property-module",
                   "smoke-vs-exhaustive", "event-schemas-and-pins", "what-anchor-does-not-check" })
        {
            Assert.NotNull(KnowledgeBase.Find(required));
        }
    }

    /// <summary>
    /// ANTI-DRIFT. Every verdict the checker can report must be explained somewhere an agent can
    /// read, or it will be reported without its caveat.
    /// </summary>
    [Fact]
    public void EveryVerdictTheCheckerCanEmitIsDocumented()
    {
        var article = KnowledgeBase.Find("reading-verdicts");
        Assert.NotNull(article);

        foreach (var verdict in new[] { "VACUOUS", "REDUNDANT", "DEAD", "live", "unknown" })
        {
            Assert.Contains(verdict, article!.Content, StringComparison.Ordinal);
        }

        // The two caveats that make a verdict honest, not merely present.
        Assert.Contains("bound", article!.Content, StringComparison.OrdinalIgnoreCase);
        // The reading: which one a verdict was computed under, and that it is Dogwood's default.
        Assert.Contains("callerPrincipal", article.Content, StringComparison.Ordinal);
    }

    /// <summary>
    /// The smoke article must not contradict the tool. If the polarity were ever written the usual
    /// way round, an agent would read it and recommend deleting a working rule.
    /// </summary>
    [Fact]
    public void TheSmokeArticleKeepsThePolarityStraight()
    {
        var article = KnowledgeBase.Find("smoke-vs-exhaustive");
        Assert.NotNull(article);

        Assert.Contains("never report VACUOUS, REDUNDANT or DEAD", article!.Content);
        Assert.Contains("Not a verdict", article.Content, StringComparison.OrdinalIgnoreCase);
    }

    /// <summary>
    /// A name reaches a lookup, so it is validated. A documentation tool that could be steered into
    /// reading arbitrary paths would be a file-disclosure tool with a friendly name.
    /// </summary>
    [Theory]
    [InlineData("../../CLAUDE")]
    [InlineData("..")]
    [InlineData("knowledge/reading-verdicts")]
    [InlineData("C:\\Windows\\win")]
    [InlineData("")]
    [InlineData("reading verdicts")]
    public void ANameCannotEscapeTheKnowledgeBase(string name)
    {
        var e = Assert.Throws<ArgumentException>(() => KnowledgeBase.ValidateName(name));

        // The refusal must say what to do next rather than merely refusing.
        Assert.Contains("ListKnowledge", e.Message);
    }

    /// <summary>The `.md` suffix is accepted, because an agent reading a URI will include it.</summary>
    [Fact]
    public void TheSuffixIsOptional()
    {
        Assert.Equal("reading-verdicts", KnowledgeBase.ValidateName("reading-verdicts.md"));
        Assert.NotNull(KnowledgeBase.Find("reading-verdicts.md"));
    }

    /// <summary>Search matches the body, not only the title.</summary>
    [Fact]
    public void SearchFindsArticlesByTheirContent()
    {
        Assert.Equal(KnowledgeBase.Articles.Count, KnowledgeBase.Search(null).Count());
        Assert.Equal(KnowledgeBase.Articles.Count, KnowledgeBase.Search("   ").Count());

        var pins = KnowledgeBase.Search("max_window").ToList();
        Assert.Contains(pins, a => a.Name == "event-schemas-and-pins");

        Assert.Empty(KnowledgeBase.Search("kubernetes"));
    }

    /// <summary>An unknown name is answered, not thrown — one bad name must not fail a batch.</summary>
    [Fact]
    public void ReadingAnUnknownArticleExplainsItself()
    {
        var read = KnowledgeTools.ReadKnowledge(["reading-verdicts", "no-such-article"]);

        Assert.Equal(2, read.Count);
        Assert.Contains("VACUOUS", read[0].Content);
        Assert.Contains("No article called", read[1].Content);
        Assert.Contains("ListKnowledge", read[1].Content);

        Assert.Throws<ArgumentException>(() => KnowledgeTools.ReadKnowledge([]));
    }

    /// <summary>Every article is also a resource, at the URI the listing advertises.</summary>
    [Fact]
    public void EveryArticleIsAlsoAResource()
    {
        var resources = KnowledgeBase.Resources().ToList();
        Assert.Equal(KnowledgeBase.Articles.Count, resources.Count);

        foreach (var a in KnowledgeBase.Articles)
        {
            Assert.Equal($"anchor://knowledge/{a.Name}", KnowledgeBase.Uri(a.Name));
            Assert.Contains(resources, r => r.ProtocolResourceTemplate.UriTemplate == KnowledgeBase.Uri(a.Name));
        }

        // The listing carries enough to choose from without reading anything.
        var summary = KnowledgeBase.Articles[0].Summary;
        Assert.Equal(KnowledgeBase.Uri(summary.Name), summary.Uri);
    }

    #endregion
}
