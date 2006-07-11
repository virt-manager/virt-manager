/* eggcellrenderersparkline.c
 * Copyright (C) 2005-2006 Red Hat, Inc.,  David Malcolm <dmalcolm@redhat.com>
 * Copyright (C) 2006 Daniel P. Berrange <berrange@redhat.com>
 *
 * This library is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Library General Public
 * License as published by the Free Software Foundation; either
 * version 2 of the License, or (at your option) any later version.
 *
 * This library is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * Library General Public License for more details.
 *
 * You should have received a copy of the GNU Library General Public
 * License along with this library; if not, write to the
 * Free Software Foundation, Inc., 59 Temple Place - Suite 330,
 * Boston, MA 02111-1307, USA.
 */

#include <stdlib.h>
#include "sparkline.h"

static void gtk_sparkline_init(GtkSparkline *cellsparkline);
static void gtk_sparkline_class_init(GtkSparklineClass *class);
static void gtk_sparkline_finalize(GObject *object);

static void gtk_sparkline_get_property(GObject *object,
				       guint param_id,
				       GValue *value,
				       GParamSpec *pspec);
static void gtk_sparkline_set_property(GObject *object,
				       guint param_id,
				       const GValue *value,
				       GParamSpec *pspec);
static void gtk_sparkline_size_request(GtkWidget *widget,
				       GtkRequisition *area);
static gboolean gtk_sparkline_expose(GtkWidget *widget,
				     GdkEventExpose *event,
				     gpointer data);

enum {
  PROP_0,
  PROP_DATAARRAY
};

static gpointer parent_class;

#define GTK_SPARKLINE_GET_PRIVATE(obj) (G_TYPE_INSTANCE_GET_PRIVATE ((obj), GTK_TYPE_SPARKLINE, GtkSparklinePrivate))

typedef struct _GtkSparklinePrivate GtkSparklinePrivate;
struct _GtkSparklinePrivate
{
  gboolean filled;
  GValueArray *data_array;
};


GType gtk_sparkline_get_type (void)
{
  static GType sparkline_type = 0;

  if (!sparkline_type) {
    static const GTypeInfo sparkline_info = {
      sizeof (GtkSparklineClass),
      NULL,		/* base_init */
      NULL,		/* base_finalize */
      (GClassInitFunc) gtk_sparkline_class_init,
      NULL,		/* class_finalize */
      NULL,		/* class_data */
      sizeof (GtkSparkline),
      0,              /* n_preallocs */
      (GInstanceInitFunc) gtk_sparkline_init,
    };

    sparkline_type =
      g_type_register_static (GTK_TYPE_DRAWING_AREA, "GtkSparkline",
			      &sparkline_info, 0);
  }

  return sparkline_type;
}

static void gtk_sparkline_init (GtkSparkline *sparkline)
{
  GtkSparklinePrivate *priv;

  priv = GTK_SPARKLINE_GET_PRIVATE (sparkline);

  priv->filled = TRUE;
  //  priv->filled = FALSE;
  priv->data_array = g_value_array_new(0);

  g_signal_connect (G_OBJECT (sparkline), "expose_event",
                    G_CALLBACK (gtk_sparkline_expose), NULL);
  //GTK_WIDGET_SET_FLAGS(GTK_WIDGET(sparkline), GTK_NO_WINDOW);
}

static void gtk_sparkline_class_init (GtkSparklineClass *class)
{
  GObjectClass *object_class = G_OBJECT_CLASS (class);
  GtkWidgetClass *widget_class = GTK_WIDGET_CLASS (class);

  parent_class = g_type_class_peek_parent (class);

  object_class->finalize = gtk_sparkline_finalize;

  object_class->get_property = gtk_sparkline_get_property;
  object_class->set_property = gtk_sparkline_set_property;

  widget_class->size_request = gtk_sparkline_size_request;
  //widget_class->expose_event = gtk_sparkline_expose;

  g_object_class_install_property (object_class,
				   PROP_DATAARRAY,
				   g_param_spec_value_array ("data_array",
							     "Data array",
							     "GValueArray of data",
							     g_param_spec_double("data_array_value",
										 "Data array value",
										 "GValueArray element",
										 0.0,
										 100.0,
										 0,
										 G_PARAM_READABLE | G_PARAM_WRITABLE),
							     G_PARAM_READABLE | G_PARAM_WRITABLE));

  g_type_class_add_private (object_class, sizeof (GtkSparklinePrivate));
}

static void gtk_sparkline_finalize (GObject *object)
{
  GtkSparkline *cellsparkline = GTK_SPARKLINE (object);
  GtkSparklinePrivate *priv;

  priv = GTK_SPARKLINE_GET_PRIVATE (object);


  (* G_OBJECT_CLASS (parent_class)->finalize) (object);
}

static void gtk_sparkline_get_property (GObject *object,
					guint param_id,
					GValue *value,
					GParamSpec *pspec)
{
  GtkSparkline *cellsparkline = GTK_SPARKLINE (object);
  GtkSparklinePrivate *priv;

  priv = GTK_SPARKLINE_GET_PRIVATE (object);

  switch (param_id)
    {
    case PROP_DATAARRAY:
      g_value_set_boxed(value, priv->data_array);
      break;

    default:
      G_OBJECT_WARN_INVALID_PROPERTY_ID (object, param_id, pspec);
      break;
    }
}

static void
gtk_sparkline_set_property (GObject      *object,
			    guint         param_id,
			    const GValue *value,
			    GParamSpec   *pspec)
{
  GtkSparkline *cellsparkline = GTK_SPARKLINE (object);
  GtkSparklinePrivate *priv;

  priv = GTK_SPARKLINE_GET_PRIVATE (object);

  switch (param_id)
    {
    case PROP_DATAARRAY:
      g_value_array_free(priv->data_array);
      priv->data_array = g_value_array_copy(g_value_get_boxed(value));
      gtk_widget_queue_draw(GTK_WIDGET(object));
      break;

    default:
      G_OBJECT_WARN_INVALID_PROPERTY_ID (object, param_id, pspec);
      break;
    }
}

static void gtk_sparkline_size_request(GtkWidget *widget,
				       GtkRequisition *area)
{
  GtkSparkline *sparkline = (GtkSparkline *) widget;
  GtkSparklinePrivate *priv;
  GValueArray *data;

  priv = GTK_SPARKLINE_GET_PRIVATE (widget);

  data = priv->data_array;

  if (area) {
    area->width = data->n_values;
    area->height = 20;
  }
}

static double get_y (GtkAllocation *cell_area,
		     GValueArray *data,
		     int index)
{
  double baseline_y = cell_area->height-1;
  GValue *val = g_value_array_get_nth(data, index);
  return baseline_y - ((cell_area->height-1) * g_value_get_double(val));
}

static gboolean
gtk_sparkline_expose (GtkWidget *widget,
		      GdkEventExpose *event,
		      gpointer extra)
{
  GtkSparklinePrivate *priv;
  GValueArray *data;
  GdkPoint *points;
  int index;
  double pixels_per_point;
  GtkAllocation *cell_area = &widget->allocation;
#if USE_CAIRO
  cairo_t *cr;
  double margin = 2;
#endif

  priv = GTK_SPARKLINE_GET_PRIVATE (widget);

  data = priv->data_array;

  pixels_per_point = (double)cell_area->width / ((double)data->n_values-1);

  points = g_new(GdkPoint, data->n_values);
  for (index=0;index<data->n_values;index++) {
    double cx = ((double)index * pixels_per_point);
    double cy = get_y (cell_area, data, index);
    points[index].x = cx;
    points[index].y = cy;
  }

  gdk_draw_rectangle(widget->window,
		     widget->style->mid_gc[GTK_WIDGET_STATE (widget)],
		     TRUE,
		     0,
		     0,
		     cell_area->width-1,
		     cell_area->height-1);
  gdk_draw_rectangle(widget->window,
		     widget->style->fg_gc[GTK_WIDGET_STATE (widget)],
		     FALSE,
		     0,
		     0,
		     cell_area->width-1,
		     cell_area->height-1);

  #define NTICKS 4
  for (index = 1 ; index < NTICKS ; index++) {
    gdk_draw_line(widget->window,
		  widget->style->dark_gc[GTK_WIDGET_STATE(widget)],
		  1,
		  cell_area->height/NTICKS*index,
		  cell_area->width-2,
		  cell_area->height/NTICKS*index);
  }

#if USE_CAIRO
  cr = gdk_cairo_create (widget->window);

  /* Clip to the cell: */
  cairo_save (cr);
  cairo_rectangle (cr, 0, 0, cell_area->width, cell_area->height);
  cairo_clip (cr);

  /* Render the line: */
  cairo_set_line_width (cr, (double)0.5);

  for (index=0;index<data->n_values;index++) {
    double cx = points[index].x;
    double cy = points[index].y;
    if (index) {
      cairo_line_to (cr, cx, cy);
    } else {
      cairo_move_to (cr, cx, cy);
    }
  }
  if (priv->filled) {
    double baseline_y = cell_area->height + cell_area->y;
    cairo_line_to (cr, cell_area->x + cell_area->width - margin, baseline_y);
    cairo_line_to (cr, 0, baseline_y);
    cairo_fill (cr);
  } else {
    cairo_stroke (cr);
  }

  /* Stop clipping: */
  cairo_restore (cr);

  cairo_destroy (cr);

#else
  gdk_draw_lines(widget->window,
		 widget->style->fg_gc[GTK_WIDGET_STATE(widget)],
		 points, data->n_values);
#endif

  g_free(points);

  return TRUE;
}

#define __GTK_SPARKLINE_C__
