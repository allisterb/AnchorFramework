namespace Anchor.MCPServer;

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text.RegularExpressions;

using ModelContextProtocol.Server;

/// <summary>
/// The knowledge base: what an agent needs to know to use these tools without over-reporting.
/// </summary>
/// <remarks>
/// <para>
/// Tool descriptions can carry a rule. They cannot carry the reasoning behind it, and the reasoning
/// is what stops a bounded answer being repeated as a proof. These articles hold the parts that do
/// not fit: why a refusal is not a pass, why a verdict is only as good as its reading, why a
/// smoke run may never claim a rule is inert.
/// </para>
/// <para>
/// EMBEDDED, not copied beside the assembly. A file on disk means a path to resolve, and a path to
/// resolve means one behaviour in the test run and another in a container. Embedding removes the
/// question.
/// </para>
/// </remarks>
public static partial class KnowledgeBase
{
    #region Properties

    /// <summary>Every article, by name, in a stable order.</summary>
    public static IReadOnlyList<Article> Articles => articles.Value;

    #endregion

    #region Methods

    /// <summary>Articles whose name, title, description or body mentions <paramref name="query"/>.</summary>
    /// <remarks>
    /// Substring, case-insensitive, over the whole article. Deliberately not clever: an agent that
    /// searched and got nothing will read the list instead, and there are few enough to read.
    /// </remarks>
    public static IEnumerable<Article> Search(string? query) =>
        string.IsNullOrWhiteSpace(query)
            ? Articles
            : Articles.Where(a =>
                a.Name.Contains(query, StringComparison.OrdinalIgnoreCase)
                || a.Title.Contains(query, StringComparison.OrdinalIgnoreCase)
                || a.Description.Contains(query, StringComparison.OrdinalIgnoreCase)
                || a.Content.Contains(query, StringComparison.OrdinalIgnoreCase));

    /// <summary>One article by name, or null. The name is validated first.</summary>
    public static Article? Find(string name)
    {
        var clean = ValidateName(name);
        return Articles.FirstOrDefault(a => a.Name.Equals(clean, StringComparison.OrdinalIgnoreCase));
    }

    /// <summary>
    /// An article name as an agent wrote it, or an exception saying why it is not one.
    /// </summary>
    /// <remarks>
    /// A name reaches a lookup, and a lookup that accepted <c>../../secrets</c> would be a file
    /// read wearing a documentation tool's name. Checked explicitly rather than relying on the
    /// lookup being a list scan today and something path-shaped tomorrow.
    /// </remarks>
    public static string ValidateName(string name)
    {
        var trimmed = (name ?? "").Trim();
        if (trimmed.EndsWith(".md", StringComparison.OrdinalIgnoreCase))
        {
            trimmed = trimmed[..^3];
        }

        string? why =
            trimmed.Length == 0 ? "it is empty"
            : trimmed.Length > 100 ? "it is longer than 100 characters"
            : trimmed.Contains('\0') ? "it contains a null byte"
            : trimmed.Contains('/') || trimmed.Contains('\\') ? "it contains a path separator"
            : trimmed.Contains("..") ? "it contains a path traversal sequence"
            : !NameShape().IsMatch(trimmed) ? "only letters, digits, hyphens and underscores are allowed"
            : null;

        return why is null
            ? trimmed
            : throw new ArgumentException(
                $"'{name}' is not an article name: {why}. Call ListKnowledge for the available names.",
                nameof(name));
    }

    /// <summary>Each article as an MCP resource, for a host that reads resources rather than tools.</summary>
    public static IEnumerable<McpServerResource> Resources() =>
        Articles.Select(a => McpServerResource.Create(
            () => a.Content,
            new McpServerResourceCreateOptions
            {
                UriTemplate = Uri(a.Name),
                Name = $"anchor-knowledge-{a.Name}",
                Title = a.Title,
                Description = a.Description,
                MimeType = "text/markdown"
            }));

    /// <summary>The canonical URI for an article, which is also how the tools refer to one.</summary>
    public static string Uri(string name) => $"anchor://knowledge/{name}";

    static IReadOnlyList<Article> Load()
    {
        var assembly = Assembly.GetExecutingAssembly();
        const string prefix = "Anchor.MCPServer.knowledge.";

        return [.. assembly.GetManifestResourceNames()
            .Where(r => r.StartsWith(prefix, StringComparison.Ordinal)
                        && r.EndsWith(".md", StringComparison.Ordinal))
            .Select(r => Parse(r[prefix.Length..^3], Read(assembly, r)))
            .OrderBy(a => a.Name, StringComparer.Ordinal)];
    }

    static string Read(Assembly assembly, string resource)
    {
        using var stream = assembly.GetManifestResourceStream(resource)!;
        using var reader = new StreamReader(stream);
        return reader.ReadToEnd();
    }

    /// <summary>
    /// Split the YAML-ish front matter off the body. Only <c>title</c> and <c>description</c> are
    /// read, and a missing one degrades to the article's name rather than failing: an article that
    /// cannot be listed because its header is malformed is worse than one listed plainly.
    /// </summary>
    static Article Parse(string name, string text)
    {
        var normalized = text.Replace("\r\n", "\n");
        var (title, description, body) = (name, "", normalized);

        var match = FrontMatter().Match(normalized);
        if (match.Success)
        {
            body = normalized[match.Length..].TrimStart('\n');
            foreach (var line in match.Groups["yaml"].Value.Split('\n'))
            {
                var colon = line.IndexOf(':');
                if (colon <= 0) continue;

                var key = line[..colon].Trim();
                var value = line[(colon + 1)..].Trim().Trim('"');
                if (key.Equals("title", StringComparison.OrdinalIgnoreCase)) title = value;
                else if (key.Equals("description", StringComparison.OrdinalIgnoreCase)) description = value;
            }
        }

        return new Article(name, title, description, body);
    }

    [GeneratedRegex(@"\A---\n(?<yaml>.*?)\n---\n", RegexOptions.Singleline)]
    private static partial Regex FrontMatter();

    [GeneratedRegex(@"\A[A-Za-z0-9_-]+\z")]
    private static partial Regex NameShape();

    #endregion

    #region Fields

    static readonly Lazy<IReadOnlyList<Article>> articles = new(Load);

    #endregion
}

/// <summary>One knowledge-base article. <paramref name="Content"/> is the body, front matter removed.</summary>
public record Article(string Name, string Title, string Description, string Content)
{
    /// <summary>The article as a listing shows it — enough to decide whether to read it.</summary>
    public ArticleSummary Summary => new(Name, Title, Description, KnowledgeBase.Uri(Name));
}

/// <summary>An article in a listing: what it is called and what it covers, without the body.</summary>
public record ArticleSummary(string Name, string Title, string Description, string Uri);
