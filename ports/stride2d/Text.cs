using System;
using Stride2D.Native.Gfx2D;

// Text from the renderer's baked DejaVu Sans fonts: a quad per glyph, laid out in screen pixels from the top left.
// Two sizes: small for the HUD and big for banners. ASCII only.
static class Text
{
    static int smallFont;
    static int bigFont;
    static int smallTex;
    static int bigTex;
    static float[] smallV;
    static float[] bigV;
    static float[] g;
    static int smallN;
    static int bigN;
    static float left;
    static float top;
    static float perPixel;
    static float screenW;
    const int MaxChars = 384;

    static float At(float[] a, int i) { return a[i]; }

    public static void Init()
    {
        smallFont = Nearest(20);
        bigFont = Nearest(40);
        smallTex = GFX.FontTexture(smallFont);
        bigTex = GFX.FontTexture(bigFont);
        smallV = new float[MaxChars * 6 * GFX.MeshVertexFloats];
        bigV = new float[MaxChars * 6 * GFX.MeshVertexFloats];
        g = new float[9];
    }

    static int Nearest(int size)
    {
        int best = 0;
        int bestGap = 100000;
        for (int i = 0; i < GFX.FontCount(); i++)
        {
            int gap = GFX.FontSize(i) - size;
            if (gap < 0) gap = -gap;
            if (gap < bestGap)
            {
                bestGap = gap;
                best = i;
            }
        }
        return best;
    }

    // The view the pixels map onto: the world rectangle the camera shows, and the picture's size in pixels.
    public static void Begin(float cx, float cy, float halfW, float halfH, int width, int height)
    {
        left = cx - halfW;
        top = cy + halfH;
        perPixel = halfH * 2f / (float)height;
        screenW = (float)width;
        smallN = 0;
        bigN = 0;
    }

    static int Code(string s, int i)
    {
        string table = " !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~";
        int k = table.IndexOf(s.Substring(i, 1));
        if (k < 0) return 63;
        return 32 + k;
    }

    // Width of the string in pixels.
    public static float Width(string s, bool big)
    {
        int font = smallFont;
        if (big) font = bigFont;
        float w = 0f;
        for (int i = 0; i < s.Length; i++)
        {
            GFX.FontGlyph(font, Code(s, i), g);
            w += At(g, 8);
        }
        return w;
    }

    static void Vert(float[] a, int n, float x, float y, float u, float v, float r, float gr, float b, float al)
    {
        int o = n * GFX.MeshVertexFloats;
        a[o] = x; a[o + 1] = y; a[o + 2] = u; a[o + 3] = v;
        a[o + 4] = r; a[o + 5] = gr; a[o + 6] = b; a[o + 7] = al;
    }

    // Draws the string with its baseline at (px, py) pixels from the top left, with a one pixel shadow.
    public static void Print(string s, float px, float py, bool big, float r, float gr, float b)
    {
        Run(s, px + 1f, py + 1f, big, 0.05f, 0.05f, 0.08f, 0.8f);
        Run(s, px, py, big, r, gr, b, 1f);
    }

    // Centred on the picture's width.
    public static void PrintCentred(string s, float py, bool big, float r, float gr, float b)
    {
        float w = Width(s, big);          // its own statement: the string is passed on right after
        Print(s, (screenW - w) * 0.5f, py, big, r, gr, b);
    }

    static void Run(string s, float px, float py, bool big, float r, float gr, float b, float a)
    {
        int font = smallFont;
        if (big) font = bigFont;
        float pen = px;
        for (int i = 0; i < s.Length; i++)
        {
            GFX.FontGlyph(font, Code(s, i), g);
            float gw = At(g, 4);
            float gh = At(g, 5);
            if (gw > 0f && gh > 0f)
            {
                float x0 = left + (pen + At(g, 6)) * perPixel;
                float x1 = x0 + gw * perPixel;
                float y1 = top - (py - At(g, 7)) * perPixel;       // the glyph's top edge
                float y0 = y1 - gh * perPixel;
                float u0 = At(g, 0);
                float v0 = At(g, 1);
                float u1 = At(g, 2);
                float v1 = At(g, 3);
                if (big) Quad(bigV, bigN, x0, y0, x1, y1, u0, v0, u1, v1, r, gr, b, a);
                else Quad(smallV, smallN, x0, y0, x1, y1, u0, v0, u1, v1, r, gr, b, a);
                if (big) bigN += 6;
                else smallN += 6;
            }
            pen += At(g, 8);
        }
    }

    static void Quad(float[] a, int n, float x0, float y0, float x1, float y1, float u0, float v0, float u1, float v1, float r, float gr, float b, float al)
    {
        if (n + 6 > MaxChars * 6) return;
        Vert(a, n, x0, y0, u0, v1, r, gr, b, al);
        Vert(a, n + 1, x1, y0, u1, v1, r, gr, b, al);
        Vert(a, n + 2, x1, y1, u1, v0, r, gr, b, al);
        Vert(a, n + 3, x0, y0, u0, v1, r, gr, b, al);
        Vert(a, n + 4, x1, y1, u1, v0, r, gr, b, al);
        Vert(a, n + 5, x0, y1, u0, v0, r, gr, b, al);
    }

    // Draws what was printed since Begin, over everything else.
    public static void Draw()
    {
        if (smallN > 0) GFX.Triangles(smallV, smallN, smallTex);
        if (bigN > 0) GFX.Triangles(bigV, bigN, bigTex);
    }
}
