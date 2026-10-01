namespace Anchor;

using System;
using System.IO;

/// <summary>
/// Resolves a caller-supplied path against the project directory, and refuses one that escapes it.
/// </summary>
/// <remarks>
/// Shared by every MCP tool that takes a path — a policy set, a property module, an event schema,
/// a <c>keep</c> directory — so that one relative path means one thing whichever tool receives it.
/// <para>
/// Containment applies to reads as well as writes. Reading is the milder of the two, but a server
/// whose whole premise is that the agent cannot reach outside its directory does not get to make an
/// exception for the direction that happens to be less alarming.
/// </para>
/// </remarks>
public static class ProjectPath
{
    #region Methods
    /// <summary>
    /// Returns the absolute path <paramref name="path"/> names inside <paramref name="projectRoot"/>.
    /// </summary>
    /// <param name="projectRoot">The project directory. When null or empty nothing is contained,
    /// which is the ad-hoc case: a server started without <c>--project-dir</c> has no project to be
    /// inside of.</param>
    /// <param name="path">The path as the script wrote it.</param>
    /// <param name="parameterName">Reported as the offending parameter.</param>
    /// <param name="action">The verb used in the message — "Write" or "Read".</param>
    /// <exception cref="OutsideProjectException">The path resolves outside the project.</exception>
    public static string Resolve(string? projectRoot, string path, string parameterName, string action)
    {
        var full = string.IsNullOrEmpty(projectRoot)
            ? Path.GetFullPath(path)
            : Path.GetFullPath(Path.Combine(projectRoot, path));

        if (string.IsNullOrEmpty(projectRoot)) return full;

        // Case-insensitive only where the filesystem is: on Linux "/a" and "/A" are different
        // directories, and ignoring case there would accept an escape as if it were contained.
        var comparison = OperatingSystem.IsWindows() ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal;

        // The trailing separator stops "C:\proj" from matching a sibling "C:\project-two".
        var contained = full.Equals(projectRoot, comparison)
            || full.StartsWith(projectRoot + Path.DirectorySeparatorChar, comparison);

        if (!contained)
        {
            throw new OutsideProjectException(
                $"'{path}' resolves to '{full}', which is outside this project's directory " +
                $"('{projectRoot}'). {action} a path inside the project, such as " +
                $"'examples/aws1/agent-policy.dw'.",
                parameterName);
        }

        return full;
    }
    #endregion
}

/// <summary>
/// A path refused because it resolves outside the project directory. A refusal, not a fault: the
/// MCP server answers it as a tool error and logs one warning line, where an exception that
/// reached the SDK was logged as an unhandled failure with a stack trace.
/// </summary>
/// <remarks>An <see cref="ArgumentException"/> still, so callers that caught that keep working.</remarks>
public class OutsideProjectException(string message, string parameterName)
    : ArgumentException(message, parameterName);
